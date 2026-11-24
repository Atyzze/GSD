from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, replace

from graph_scale_dynamics.decisions import gates as G

CONTRACT = "gsd-let-through-ledger-1"
NOT_A_VERDICT = frozenset({"start", "complete_rung", "longer_chain", "lane_resumed", "hold_released",
                           "deep_lane_full", "lane_yielded", "ladder_complete", "over_budget"})
WITHHOLDING_ACTIONS = ("stop", "hold")
CLEAN, MISSED, OPEN = "clean", "missed", "open"
KNOWN_RESULT = "repeats_a_known_result"
PRICED = "over_budget"


def salted_of(facts) -> list[str]:
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except ValueError:
            return []
    found = (facts or {}).get("salted") if isinstance(facts, dict) else facts
    return [str(G.today(gate)) for gate in (found or []) if isinstance(gate, str)]


@dataclass
class Counter_:
    let_through: int = 0
    clean: int = 0
    same_gate: int = 0
    missed: int = 0
    clean_since_last_miss: int = 0
    held: int = 0
    priced: int = 0

    def as_dict(self) -> dict:
        return {"held": self.held, "priced": self.priced, "let_through": self.let_through, "clean": self.clean, "same_gate": self.same_gate,
                "missed": self.missed, "open": self.let_through - self.clean - self.missed,
                "clean_since_last_miss": self.clean_since_last_miss}


@dataclass
class Ledger:
    counters: dict = field(default_factory=dict)
    open: dict = field(default_factory=dict)
    judged: set = field(default_factory=set)
    signatures: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    seen_counted: set = field(default_factory=set)
    held: set = field(default_factory=set)
    passed: dict = field(default_factory=dict)
    last: str = ""
    rows: int = 0
    counts_priced: bool = False

    def feed(self, row: dict) -> None:
        self.rows += 1
        self.last = max(self.last, str(row.get("decision_id") or ""))
        key = (str(row.get("campaign_id")), str(row.get("candidate_id")))
        at_n = row.get("at_n")
        if at_n is None:
            return
        at_n = int(at_n)
        action, rule = str(row.get("action")), str(G.today(row.get("rule")))
        salted = salted_of(row.get("salted"))
        verdict = rule not in NOT_A_VERDICT
        if rule == "failed":
            self.open.pop(key, None)
            return
        if verdict:
            self._judge(key, at_n, action, rule, salted)
            if action in WITHHOLDING_ACTIONS and rule in G.BY_NAME and (key, rule, at_n) not in self.held:
                self.held.add((key, rule, at_n))
                self._counter(rule, at_n).held += 1
        elif self.counts_priced and rule == PRICED and salted:
            self._judge(key, at_n, action, rule, salted)
            for gate in salted:
                if gate in G.BY_NAME and (key, gate, at_n) not in self.held:
                    self.held.add((key, gate, at_n))
                    self._counter(gate, at_n).priced += 1
        self._signature(key, at_n, row.get("signature"))
        if salted and action in ("run_next", "hold"):
            for gate in salted:
                event = (gate, at_n)
                if (key, event) in self.judged or event in self.open.get(key, ()):
                    continue
                self.open.setdefault(key, set()).add(event)
                self._counter(gate, at_n).let_through += 1
                self.passed.setdefault(event, set()).add(key)

    def _counter(self, gate: str, n: int) -> Counter_:
        return self.counters.setdefault((str(gate), int(n)), Counter_())

    def _judge(self, key, at_n: int, action: str, rule: str, salted: list) -> None:
        events = [event for event in self.open.get(key, ()) if event[1] < at_n]
        if not events:
            return
        withheld = action in WITHHOLDING_ACTIONS or bool(salted)
        for gate, n in events:
            counter = self._counter(gate, n)
            if withheld:
                counter.clean += 1
                counter.clean_since_last_miss += 1
                if gate == rule or gate in salted:
                    counter.same_gate += 1
            else:
                counter.missed += 1
                counter.clean_since_last_miss = 0
            self.open[key].discard((gate, n))
            self.judged.add((key, (gate, n)))

    def _signature(self, key, at_n: int, signature) -> None:
        if not signature:
            return
        signature = str(signature)
        mine = self.signatures.setdefault(key, {})
        below = [n for n in mine if n < at_n]
        if below and (key, max(below)) not in self.seen_counted:
            n = max(below)
            self.seen_counted.add((key, n))
            entry = self.seen.setdefault((mine[n], n), [0, 0])
            entry[1] += 1
            if mine[n] == signature:
                entry[0] += 1
        mine.setdefault(at_n, signature)

    def share(self, gate: str, n: int, policy) -> float:
        if int(n) < int(policy.let_through_from) or not policy.asks_for(gate) or int(n) < policy.acts_from(gate):
            return G.RECORD_ONLY
        if policy.own_share(gate) is not None:
            return policy.own_share(gate)
        if policy.ab_share:
            return float(policy.ab_share)
        counter = self.counters.get((str(gate), int(n)))
        if counter is not None and counter.clean_since_last_miss >= int(policy.confirm_after):
            return G.CONFIRMED_SHARE
        return G.TESTING_SHARE

    def shares(self, policy) -> tuple:
        return tuple(sorted((gate, n, self.share(gate, n, policy)) for gate, n in self.counters
                            if int(n) >= int(policy.let_through_from)))

    def known_results(self, policy) -> tuple:
        after = int(policy.known_result_after or 0)
        if after <= 0:
            return ()
        return tuple(sorted((int(n), str(signature)) for (signature, n), (same, _read) in self.seen.items()
                            if int(n) >= policy.known_result_size() and same >= after))

    def document(self, policy, *, signatures: int | None = 200, scores: dict | None = None,
                 laws: bool = False) -> dict:
        gates = {}
        for (gate, n), counter in sorted(self.counters.items()):
            share = self.share(gate, n, policy)
            label = ("records only" if share >= 1.0 else "closed" if share <= 0.0 else "A/B" if policy.ab_share
                     else "confirmed" if share <= G.CONFIRMED_SHARE else "testing")
            entry = dict(counter.as_dict(), share=share, label=label)
            entry["held"] = counter.held + (counter.priced if share < 1.0 else 0)
            passed = sorted(self.passed.get((gate, n), ()))
            if scores is not None:
                found = sorted(((float(scores[key]), key) for key in passed
                                if isinstance(scores.get(key), (int, float)) and scores[key] > 0), reverse=True)
                entry.update(scored=len(found), best_score=found[0][0] if found else None,
                             best_law=list(found[0][1]) if found else None)
            if laws:
                entry["laws"] = [f"{campaign}:{law}" for campaign, law in passed]
            gates.setdefault(gate, {})[str(n)] = entry
        seen = sorted(((signature, n, same, read) for (signature, n), (same, read) in self.seen.items()),
                      key=lambda row: (-row[2], row[1], row[0]))
        return {"contract": CONTRACT, "rule": G.LET_THROUGH_RULE, "from_n": int(policy.let_through_from),
                "confirm_after": int(policy.confirm_after), "known_result_after": int(policy.known_result_after or 0),
                "known_result_from": policy.known_result_size(),
                "ab_share": float(policy.ab_share), "about": G.about(),
                "testing_share": G.TESTING_SHARE, "confirmed_share": G.CONFIRMED_SHARE, "decisions_read": self.rows,
                "gates": gates,
                "signatures": [{"signature": signature, "n": n, "kept": same, "read_one_size_up": read,
                                "known": bool(policy.known_result_after and n >= policy.known_result_size()
                                                    and same >= int(policy.known_result_after))}
                               for signature, n, same, read in (seen if signatures is None else seen[:signatures])],
                "signatures_total": len(seen),
                "reading": ("Every gate at every size, from this study's own decisions only: held is the laws it "
                            "held back there, each once, with the laws its budget stopped while it stood against them "
                            "(priced) only where the gate acts; let_through is the laws "
                            "it would have withheld that went one size on; clean the ones withheld again there "
                            "(same_gate: by the same gate); missed the ones that passed every gate there; open the "
                            "ones not judged yet. Below from_n every verdict is recorded and every law goes on; from "
                            "it a gate lets 10% through until confirm_after clean in a row, then 1%, and a miss puts "
                            "it back; with ab_share every gate lets that share of the laws through, each law's arm drawn "
                            "once for the gate, and none confirms; a gate the design gives its own share "
                            "(gate_shares) keeps it, 1 recording only and 0 closed. scored, where present, is how "
                            "many of the "
                            "let-through laws score above zero and best_score the best of them. A "
                            "signature is what each chain is at a size from known_result_from; known once that "
                            "many laws kept it one size up.")}


def ledger_from_rows(rows, policy=None) -> Ledger:
    ledger = Ledger(counts_priced=bool(getattr(policy, "ledger_counts_priced", False)))
    for row in rows:
        ledger.feed(row)
    return ledger


LEARNING_CONTRACT = "gsd-learning-at-fixed-points-1"
LEARNING = "learning"


def learned_gates(policy) -> list[str]:
    if policy.ab_share:
        return []
    return sorted(gate for gate in G.LET_THROUGH_GATES if policy.asks_for(gate) and policy.own_share(gate) is None)


def known_results_learned(policy) -> bool:
    if int(policy.known_result_after or 0) <= 0 or not policy.asks_for(KNOWN_RESULT):
        return False
    own = policy.own_share(KNOWN_RESULT)
    return own is None or float(own) < G.RECORD_ONLY


def learns(policy, n) -> bool:
    if not getattr(policy, "let_through_rule", "") or n is None:
        return False
    sizes = []
    if learned_gates(policy):
        sizes.append(int(policy.let_through_from))
    if known_results_learned(policy):
        sizes.append(int(policy.known_result_size()))
    return bool(sizes) and int(n) >= min(sizes)


def batch_of(number: int, policy) -> int:
    return (max(1, int(number)) - 1) // max(1, int(policy.learn_in_batches_of))


def past(law: dict, n: int) -> bool:
    top = law.get("verdict_past")
    return bool(law.get("ended")) or (top is not None and int(top) > int(n))


def settled(law: dict, n: int) -> bool:
    top = law.get("verdict_past")
    return bool(law.get("ended")) or (not law.get("held") and top is not None and int(top) >= int(n))


def records_only(policy, gate: str, n: int) -> bool:
    return float(policy.live_share(gate, n)) >= 1.0


@dataclass
class FixedPoints:
    laws: list = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    ledgers: dict = field(default_factory=dict)
    fed: dict = field(default_factory=dict)
    read: list = field(default_factory=list)
    drawing: dict = field(default_factory=dict)
    size: int = 100
    members: dict = field(default_factory=dict)
    read_at: dict = field(default_factory=dict)
    counts_priced: bool = False

    def refresh(self, laws: list, policy, own: str | None = None, read: list | None = None,
                drawing: dict | None = None) -> "FixedPoints":
        self.laws = list(laws)
        self.size = max(1, int(policy.learn_in_batches_of))
        self.counts_priced = bool(getattr(policy, "ledger_counts_priced", False))
        self.read = [[str(c), int(place)] for c, place in (read or [])]
        self.drawing = {str(c): dict(state) for c, state in (drawing or {}).items()}
        self.numbers = {str(law["candidate_id"]): int(law["number"]) for law in self.laws
                        if own is None or str(law["campaign_id"]) == str(own)}
        groups: dict = {}
        for law in self.laws:
            groups.setdefault(batch_of(law["number"], policy), []).append(law)
        for rows in groups.values():
            rows.sort(key=lambda law: (int(law["number"]), int(law["campaign_order"]), str(law["campaign_id"])))
        self.groups = groups
        return self

    def before(self, batch: int) -> int:
        return sum(len(self.groups.get(b, ())) for b in range(int(batch)))

    def closed(self, group: int) -> bool:
        last = (int(group) + 1) * self.size
        return all(state.get("finished") or int(state.get("top") or 0) >= last for state in self.drawing.values())

    def _keys(self, group: int) -> tuple:
        return tuple((str(law["campaign_id"]), str(law["candidate_id"])) for law in self.groups.get(group, ()))

    def ledger(self, batch: int, n: int, rows_of) -> Ledger | None:
        n, batch = int(n), int(batch)
        kept = self.members.get(n, {})
        if any(self._keys(group) != keys for group, keys in kept.items()):
            self.ledgers[n], self.fed[n], self.members[n] = Ledger(counts_priced=self.counts_priced), 0, {}
        ledger = self.ledgers.setdefault(n, Ledger(counts_priced=self.counts_priced))
        fed = self.fed.get(n, 0)
        while fed < batch:
            laws = self.groups.get(fed, [])
            if not self.closed(fed) or not all(past(law, n) for law in laws):
                return None
            for row in rows_of([(law["campaign_id"], law["candidate_id"]) for law in laws]):
                ledger.feed(row)
            self.members.setdefault(n, {})[fed] = self._keys(fed)
            fed += 1
            self.fed[n] = fed
        if fed > batch:
            return FixedPoints(self.laws, self.numbers, self.groups, read=self.read, drawing=self.drawing,
                               size=self.size, counts_priced=self.counts_priced).ledger(batch, n, rows_of)
        return ledger

    def determined(self, batch: int, n: int, policy, rows_of) -> dict | None:
        n, batch = int(n), int(batch)
        if not all(self.closed(group) for group in range(batch)):
            return None
        earlier = [law for group in range(batch) for law in self.groups.get(group, ())]
        undecided = sum(1 for law in earlier if not settled(law, n))
        gates = n >= int(policy.let_through_from) and bool(learned_gates(policy))
        signatures = (known_results_learned(policy) and n >= int(policy.known_result_size())
                      and not records_only(policy, KNOWN_RESULT, n))
        let_through, alike = Counter(), Counter()
        if gates or signatures:
            for salted, signed in self._read_at(earlier, n, rows_of):
                let_through.update(gate for gate in salted if policy.own_share(gate) is None)
                alike.update(signed)
        most, same = max(let_through.values(), default=0), max(alike.values(), default=0)
        if gates and undecided + most >= int(policy.confirm_after):
            return None
        if signatures and undecided + same >= int(policy.known_result_after):
            return None
        return {"undecided": undecided, "let_through_most": most, **({"alike_most": same} if signatures else {})}

    def _read_at(self, earlier: list, n: int, rows_of) -> list:
        state = {(str(law["campaign_id"]), str(law["candidate_id"])):
                 (law.get("verdict_past"), bool(law.get("ended")), bool(law.get("held")))
                 for law in earlier if law.get("verdict_past") is not None and int(law["verdict_past"]) >= n}
        missing = [key for key, now in state.items() if (self.read_at.get((n, key)) or (None,))[0] != now]
        if missing:
            found = {key: (set(), set()) for key in missing}
            for row in rows_of(missing):
                key = (str(row.get("campaign_id")), str(row.get("candidate_id")))
                if key not in found or row.get("at_n") is None or int(row["at_n"]) != n:
                    continue
                if str(row.get("action")) in ("run_next", "hold"):
                    found[key][0].update(salted_of(row.get("salted")))
                if row.get("signature"):
                    found[key][1].add(str(row["signature"]))
            for key in missing:
                self.read_at[(n, key)] = (state[key], *found[key])
        return [self.read_at[(n, key)][1:] for key in state]


def at_size(rows: tuple, n: int) -> tuple:
    return tuple(row for row in rows if int(row[1] if len(row) == 3 else row[0]) == int(n))


def learned_policy(policy, ledger: Ledger, n: int):
    return replace(policy, salt_shares=at_size(ledger.shares(policy), n),
                   known_results=() if records_only(policy, KNOWN_RESULT, n)
                   else at_size(ledger.known_results(policy), n))


def determined_policy(policy):
    return replace(policy, salt_shares=(), known_results=())


__all__ = ["CLEAN", "CONTRACT", "FixedPoints", "LEARNING", "LEARNING_CONTRACT", "Ledger", "MISSED", "NOT_A_VERDICT",
           "KNOWN_RESULT", "OPEN", "at_size", "batch_of", "determined_policy", "known_results_learned", "learned_gates",
           "learned_policy", "learns",
           "ledger_from_rows", "past", "records_only", "salted_of", "settled"]
