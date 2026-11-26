from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from typing import Protocol

from graph_scale_dynamics.decisions.by_word import run_on
from graph_scale_dynamics.decisions.memory_ceiling import settle as memory_settle
from graph_scale_dynamics.decisions.engine import (
    DONE, ENGINE_VERSION, HOLD, LANE_AUDIT, LANE_FAMILY, LANE_ORDER, PARKING_RULES, RUN_NEXT, STOP,
    Decision, Policy, Seed, decide, policy_fingerprint, rules_revision)
from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES, CandidateState
from graph_scale_dynamics.decisions.every_chain import EMPTY, chain_structure, decide_every_chain
from graph_scale_dynamics.decisions.rungs import rung_from_entry

QUEUE_ORDER = {"base": 10, 1: 20, 2: 30, 3: 40, "held": 90}

STATE_BY_ACTION = {STOP: CandidateState.STOPPED.value, DONE: CandidateState.DONE.value,
                   HOLD: CandidateState.HELD.value}


def _running_state(decision: Decision, policy: Policy) -> str:
    next_n = decision.next_n
    if next_n is None or int(next_n) <= int(policy.base_sizes[-1]):
        return CandidateState.BASE_BLOCK_RUNNING.value
    return CandidateState.EXTENDING.value


def _terminal_state(decision: Decision) -> str:
    if decision.rule in PARKING_RULES:
        return CandidateState.PARKED.value
    return STATE_BY_ACTION[decision.action]


DECIDE_AGAIN = "decide again"
MADE_NO_WORK = "made no work"

class Store(Protocol):
    def laws_awaiting_decision(self, campaign_id: str) -> list: ...
    def law_evidence(self, campaign_id: str, law: str) -> dict: ...
    def record_phenotype(self, campaign_id: str, law: str, phenotype) -> None: ...
    def seed_rows(self, campaign_id: str, law: str) -> dict: ...
    def enqueue_seeds(self, campaign_id: str, law: str, n: int, *, seeds: int,
                      work_budget: int, queue_order: int) -> int: ...
    def set_law_state(self, campaign_id: str, law: str, state: str, *, rule: str, next_n) -> int: ...
    def record_decision(self, campaign_id: str, row: dict) -> None: ...
    def queue_depth(self, campaign_id: str) -> int: ...
    def held_laws(self, campaign_id: str) -> list: ...


def _rungs(store: Store, campaign_id: str, law: str, entries: dict, structure: dict | None = None,
           longer_chains=()) -> list:
    seeds = store.seed_rows(campaign_id, law) or {}
    structure = {int(n): value for n, value in (structure or {}).items()}
    longer = {int(n) for n in longer_chains or ()}
    rungs = []
    for n in sorted(entries, key=int):
        rung_seeds = [Seed(termination=row.get("ended"), given_at_cap=bool(row.get("given_at_cap")),
                           **{key: row.get(key) for key in SEED_WORK_KEYS if isinstance(row.get(key), int)})
                      for row in seeds.get(int(n), [])]
        rung = rung_from_entry(int(n), entries[n], rung_seeds, structure=structure.get(int(n)),
                               longer_chain=int(n) in longer)
        if rung is not None:
            rungs.append(rung)
    return rungs


SEED_WORK_KEYS = ("work_units", "moves", "first_chunk_units", "first_chunk_moves", "first_multiplier",
                  "final_multiplier", "work_budget")
DECISION_INPUTS_CONTRACT = "decision-inputs-1"


def _given_rungs(store: Store, campaign_id: str, law: str, evidence: dict, policy: Policy) -> dict | None:
    if not policy.every_chain or not evidence.get("entries"):
        return None
    structure = {int(n): value for n, value in (evidence.get("structure") or {}).items()}
    out = {EMPTY: _rungs(store, campaign_id, law, evidence.get("entries") or {},
                           chain_structure(structure, -1, EMPTY), evidence.get("longer_chains"))}
    for index, (name, cells) in enumerate((evidence.get("chains") or {}).items()):
        own = chain_structure(structure, index, name)
        out[str(name)] = _rungs(store, campaign_id, law, cells or {}, own, evidence.get("longer_chains"))
    return out


def decision_inputs(law: str, rungs: list, policy: Policy, *, failed_seeds=None, failed_analyses=None,
                    standing=None, deep_lane_in_flight=None, gate=None, chains=None, starts_reading=None,
                    evidence_failed=None, graphs_to_n=None, learned=None) -> dict:
    return {"contract": DECISION_INPUTS_CONTRACT, "law": str(law),
            **({"chains": {str(name): [asdict(rung) for rung in rows] for name, rows in chains.items()},
                "chain_order": [str(name) for name in chains], "last_rung_completes": True}
               if chains is not None else {}),
            "rungs": [asdict(rung) for rung in rungs],
            "failed_seeds": {str(k): v for k, v in (failed_seeds or {}).items()},
            "failed_analyses": {str(k): v for k, v in (failed_analyses or {}).items()},
            "standing": standing,
            "deep_lane_in_flight": ({str(k): v for k, v in deep_lane_in_flight.items()}
                                    if isinstance(deep_lane_in_flight, dict) else deep_lane_in_flight),
            "gate": (dict(gate) if gate is not None else None),
            **({"starts_reading": starts_reading} if starts_reading is not None else {}),
            **({"evidence_failed": str(evidence_failed)} if evidence_failed else {}),
            **({"graphs_to_n": int(graphs_to_n)} if evidence_failed and graphs_to_n else {}),
            **({"learned": dict(learned)} if learned else {}),
            "policy": asdict(policy), "policy_fingerprint": policy_fingerprint(policy),
            "rules_revision": rules_revision(policy), "engine": ENGINE_VERSION}


def _queue_order(decision: Decision, policy: Policy) -> int:
    if decision.rule in ("start", "base_block", "complete_rung"):
        return QUEUE_ORDER["base"]
    if decision.next_n is not None and int(decision.next_n) <= int(policy.base_sizes[-1]):
        return QUEUE_ORDER["base"]
    return QUEUE_ORDER.get(decision.priority, QUEUE_ORDER["held"])


def _refused(store: Store, campaign_id: str, law: str, parked_ok: bool) -> str | None:
    check = getattr(store, "law_refuses_running", None)
    if not callable(check):
        return None
    return check(campaign_id, law, **({"parked_ok": True} if parked_ok else {}))


def apply(store: Store, campaign_id: str, decision: Decision, policy: Policy, *, released: bool = False,
          parked_ok: bool = False) -> dict:
    parked = {"parked_ok": True} if parked_ok else {}
    target = _running_state(decision, policy) if decision.action == RUN_NEXT else _terminal_state(decision)
    if target in RUNNING_CANDIDATE_STATES:
        refused = _refused(store, campaign_id, decision.law, parked_ok)
        if refused is not None:
            return {"jobs_created": 0, "rows_changed": 0, "queue_order": None, "refused": str(refused)}
    if decision.action == RUN_NEXT:
        order = QUEUE_ORDER["held"] if released else _queue_order(decision, policy)
        longer = {"longer": True} if decision.rule == "longer_chain" else {}
        from graph_scale_dynamics.decisions.depth import budget_scale
        scale = 1.0 if released else budget_scale(decision, policy)
        longer.update({"budget_scale": scale} if scale != 1.0 else {})
        created = store.enqueue_seeds(campaign_id, decision.law, int(decision.next_n), seeds=policy.seeds,
                                      work_budget=int(policy.work_budget(int(decision.next_n)) * scale),
                                      queue_order=order, **longer)
        changed = store.set_law_state(campaign_id, decision.law, target, rule=decision.rule, next_n=decision.next_n,
                                      **parked)
        return {"jobs_created": int(created), "rows_changed": int(changed), "queue_order": order}
    changed = store.set_law_state(campaign_id, decision.law, target, rule=decision.rule, next_n=decision.next_n,
                                  **(parked if target in RUNNING_CANDIDATE_STATES else {}))
    return {"jobs_created": 0, "rows_changed": int(changed), "queue_order": None}


@contextmanager
def _one_transaction(store: Store):
    unit = getattr(store, "one_transaction", None)
    if not callable(unit):
        yield
        return
    with unit():
        yield


def _no_work(store: Store, campaign_id: str, decision: Decision) -> dict:
    working = getattr(store, "law_has_work", None)
    if not callable(working) or working(campaign_id, decision.law):
        return {}
    read = getattr(store, "size_is_read", None)
    again = getattr(store, "bought_the_same_with_no_work", None)
    if (callable(read) and not read(campaign_id, decision.law, int(decision.next_n))) or (
            callable(again) and again(campaign_id, decision.law, int(decision.next_n), decision.rule)):
        return {"made_no_work": MADE_NO_WORK}
    return {"made_no_work": DECIDE_AGAIN}


def _apply_and_record(store: Store, campaign_id: str, decision: Decision, policy: Policy, row: dict, *,
                      released: bool = False, parked_ok: bool = False) -> dict:
    with _one_transaction(store):
        effect = apply(store, campaign_id, decision, policy, released=released, parked_ok=parked_ok)
        if effect.get("refused") is None:
            if decision.action == RUN_NEXT and not int(effect.get("jobs_created") or 0):
                effect.update(_no_work(store, campaign_id, decision))
            store.record_decision(campaign_id, decision.as_dict() | effect | row)
    return effect


def _carry(facts: dict) -> dict:
    keep = ("lane", "salted", "salted_from", "plateau", "gate")
    return {key: facts[key] for key in keep if key in (facts or {})}


def _yield_lanes(store: Store, campaign_id: str, policy: Policy, lanes: dict, tally: Counter) -> dict:
    merit = getattr(store, "laws_waiting_for_the_lane", None)
    audit = getattr(store, "audit_laws_in_flight_at", None)
    park = getattr(store, "park_lane_seeds", None)
    if not (callable(merit) and callable(audit) and callable(park)):
        return {}
    gave: dict = {}
    for n, count in lanes.items():
        if count is None:
            continue
        width = policy.deep_lane_width(n)
        waiting = list(merit(campaign_id, n, limit=width, merit_only=True) or [])
        short = len(waiting) - max(0, width - count)
        if short <= 0:
            continue
        for entry, to in zip((audit(campaign_id, n) or [])[:short], waiting, strict=False):
            facts = dict(_carry(entry.get("facts") or {}))
            lane = dict(facts.get("lane") or {})
            lane.update(audit=True, rank=(LANE_FAMILY if lane.get("family") else LANE_AUDIT))
            lane["queue"] = LANE_ORDER[lane["rank"]]
            with _one_transaction(store):
                refused = _refused(store, campaign_id, entry["law"], False)
                effect = {"refused": refused}
                if refused is None:
                    seeds = park(campaign_id, entry["law"], int(n))
                    facts.update(lane=lane, yielded={"to": str(to), "at_n": int(n), **seeds})
                    decision = Decision(law=entry["law"], action=HOLD, rule="deep_lane_full",
                                        reason=(f"gave its place in the N={int(n):,} lane to {str(to)[:12]}, a law "
                                                "bought on its own reading (537, C4): this law is there for audit's "
                                                "sake, and waits behind such laws; its chains are saved where they "
                                                "stand and resume when the lane has room"),
                                        at_n=entry.get("at_n"), next_n=int(n), priority=entry.get("priority"),
                                        facts=facts)
                    effect = _apply_and_record(store, campaign_id, decision, policy,
                                               {"released_hold": False, "inputs": None,
                                                "context": {"lane_occupancy": {str(k): v for k, v in lanes.items()},
                                                            "yielded_to": str(to)}})
            if effect.get("refused") is not None:
                tally[("refused", str(effect["refused"]))] += 1
                continue
            lanes[n] -= 1
            gave.setdefault(n, []).append(entry["law"])
            tally[(HOLD, "lane_yielded")] += 1
    return gave


def _resume(store: Store, campaign_id: str, law: str, policy: Policy, lanes: dict, tally: Counter) -> bool:
    parked_rung = getattr(store, "parked_rung", None)
    wake = getattr(store, "wake_lane_seeds", None)
    latest = getattr(store, "latest_decision", None)
    if not (callable(parked_rung) and callable(wake)):
        return False
    n = parked_rung(campaign_id, law)
    if n is None:
        return False
    before = (latest(campaign_id, law) if callable(latest) else None) or {}
    with _one_transaction(store):
        refused = _refused(store, campaign_id, law, False)
        if refused is not None:
            tally[("refused", str(refused))] += 1
            return True
        woken = int(wake(campaign_id, law, int(n)))
        decision = Decision(law=law, action=RUN_NEXT, rule="lane_resumed",
                            reason=(f"the N={int(n):,} lane has room again: the chains this law saved when it gave "
                                    "the lane up resume where they stopped (537, C4)"),
                            at_n=before.get("at_n"), next_n=int(n), priority=before.get("priority"),
                            facts=dict(_carry(before.get("facts") or {}), resumed={"at_n": int(n), "seeds": woken}))
        changed = store.set_law_state(campaign_id, law, _running_state(decision, policy), rule=decision.rule,
                                      next_n=decision.next_n)
        effect = {"jobs_created": 0, "rows_changed": int(changed), "queue_order": None}
        store.record_decision(campaign_id, decision.as_dict() | effect
                              | {"released_hold": False, "inputs": None,
                                 "context": {"lane_occupancy": {str(k): v for k, v in lanes.items()}}})
    if lanes.get(int(n)) is not None:
        lanes[int(n)] += 1
    tally[(RUN_NEXT, "lane_resumed")] += 1
    return True


def failure_text(error: BaseException) -> str:
    import traceback
    ours = [frame for frame in traceback.extract_tb(error.__traceback__)
            if "/graph_scale_dynamics/" in frame.filename.replace("\\", "/")]
    where = ""
    if ours:
        frame = ours[-1]
        path = frame.filename.replace("\\", "/").rsplit("/graph_scale_dynamics/", 1)[-1]
        where = f" at {path}:{frame.lineno} in {frame.name}"
    return f"{type(error).__name__}: {error}{where}"


def transient(error: BaseException) -> bool:
    seen = 0
    while error is not None and seen < 8:
        if getattr(error, "transient", False) is True:
            return True
        error, seen = (error.__cause__ or error.__context__), seen + 1
    return False


def _graphs_to_n(store: Store, campaign_id: str, law: str) -> int | None:
    largest = getattr(store, "largest_graph_n", None)
    return largest(campaign_id, law) if callable(largest) else None


def _stop_undecidable(store: Store, campaign_id: str, law: str, policy: Policy, why: str, tally: Counter) -> None:
    try:
        top = _graphs_to_n(store, campaign_id, law)
        decision = decide(law, [], policy, evidence_failed=why, graphs_to_n=top)
        effect = _apply_and_record(store, campaign_id, decision, policy,
                                   {"released_hold": False,
                                    "inputs": decision_inputs(law, [], policy, evidence_failed=why, graphs_to_n=top),
                                    "context": {"undecidable": why}})
        tally[(decision.action, "undecidable") if effect.get("refused") is None
              else ("refused", str(effect["refused"]))] += 1
    except Exception as error:  # noqa: BLE001
        tally[("failed", type(error).__name__)] += 1


REDO_KEPT_EVERY = 200


def _keep_redo(store: Store, campaign_id: str, rules: str, redo: set) -> None:
    keep = getattr(store, "record_rules_redo_left", None)
    if callable(keep):
        keep(campaign_id, rules, sorted(redo))


def learning_of(store: Store, campaign_id: str, policy: Policy):
    if not policy.let_through_rule:
        return None
    points, rows = getattr(store, "fixed_points", None), getattr(store, "learning_rows", None)
    if not (callable(points) and callable(rows)):
        return None
    return points(campaign_id)


def learned_for(store: Store, points, policy: Policy, law: str, top_n) -> tuple[Policy | None, dict | None]:
    from graph_scale_dynamics.decisions import let_through as LT
    if points is None or not LT.learns(policy, top_n):
        return policy, None
    number = points.numbers.get(str(law))
    if number is None:
        return policy, None
    batch = LT.batch_of(number, policy)
    ledger = points.ledger(batch, int(top_n), store.learning_rows)
    found = points.determined(batch, int(top_n), policy, store.learning_rows) if ledger is None else None
    if ledger is None and found is None:
        return None, None
    learned = {"contract": LT.LEARNING_CONTRACT, "number": int(number), "batch": int(batch), "at_n": int(top_n),
               "laws_learned_from": points.before(batch),
               **({"decisions_read": int(ledger.rows)} if ledger is not None else {"determined": found}),
               **({"campaigns": [list(pair) for pair in points.read]} if len(points.read) > 1 else {})}
    if ledger is None:
        return LT.determined_policy(policy), learned
    return LT.learned_policy(policy, ledger, int(top_n)), learned


def decide_pass(store: Store, campaign_id: str, policy: Policy = Policy(), *, hold_release_limit: int = 64) -> Counter:
    tally: Counter = Counter()
    points = learning_of(store, campaign_id, policy)
    base_policy = policy
    counter = getattr(store, "laws_in_flight_at", None)
    waiting = getattr(store, "laws_waiting_for_the_lane", None)
    lanes = {n: (int(counter(campaign_id, n)) if callable(counter) else None)
             for n in policy.lane_rungs()}
    stray = getattr(store, "wake_stray_seeds", None)
    if callable(stray):
        stray(campaign_id)
    _yield_lanes(store, campaign_id, policy, lanes, tally)
    again = []
    competing: dict = {}
    for n, count in lanes.items():
        room = (policy.deep_lane_width(n) - count) if count is not None else 0
        if callable(waiting) and room > 0:
            offered = list(waiting(campaign_id, n, limit=room) or [])
            competing[str(n)] = [str(law) for law in offered]
            again += [law for law in offered if law not in again]
    queue_at_start = int(store.queue_depth(campaign_id))
    enqueued = 0
    awaiting = list(store.laws_awaiting_decision(campaign_id) or [])
    rules = policy_fingerprint(policy)
    reader = getattr(store, "decision_rules_fingerprint", None)
    writer = getattr(store, "record_decision_rules_fingerprint", None)
    redo = None
    parked_redo: set = set()
    if callable(reader) and callable(writer) and reader(campaign_id) != rules:
        held_now = [str(h["law"]) for h in (store.held_laws(campaign_id, limit=100000) or [])]
        parked = getattr(store, "parked_laws", None)
        parked_now = ([str(law) for law in (parked(campaign_id) or [])]
                      if policy.every_chain and callable(parked) else [])
        again_now = held_now + [law for law in parked_now if law not in held_now]
        left = getattr(store, "rules_redo_left", None)
        undone = left(campaign_id, rules) if callable(left) else None
        if undone is not None:
            again_now = [law for law in again_now if law in undone]
        awaiting = again_now + [law for law in awaiting if law not in again_now]
        redo = set(again_now)
        parked_redo = {law for law in parked_now if law in redo and law not in held_now}
        tally[("rules_changed", rules)] += len(again_now)
    named = getattr(store, "run_on_laws", None)
    by_word = dict(named(campaign_id) or {}) if callable(named) else {}
    ceilinged = getattr(store, "memory_ceilings", None)
    ceilings = dict(ceilinged(campaign_id) or {}) if callable(ceilinged) else {}
    parked_redo |= set(by_word)
    order = again + [law for law in by_word if law not in again]
    order += [law for law in awaiting if law not in order]
    reader_of_the_gate = getattr(store, "gate_context", None)
    gate = dict(reader_of_the_gate(campaign_id) or {}) if (order and callable(reader_of_the_gate)) else {}
    for position, law in enumerate(order):
        try:
            if law in again and _resume(store, campaign_id, str(law), policy, lanes, tally):
                (redo or set()).discard(str(law))
                continue
            evidence = store.law_evidence(campaign_id, str(law)) or {}
            if evidence.get("pending"):
                pending = getattr(store, "record_pending", None)
                if callable(pending):
                    pending(campaign_id, str(law), list(evidence.get("pending_reasons") or []))
                for reason in evidence.get("pending_reasons") or ["pending"]:
                    tally[("pending", str(reason))] += 1
                continue
            top_n = max((int(n) for n in (evidence.get("entries") or {})), default=None)
            policy, learned = learned_for(store, points, base_policy, str(law), top_n)
            if policy is None:
                pending = getattr(store, "record_pending", None)
                if callable(pending):
                    pending(campaign_id, str(law), ["learning"])
                tally[("pending", "learning")] += 1
                policy = base_policy
                continue
            rungs = _rungs(store, campaign_id, str(law), evidence.get("entries") or {}, evidence.get("structure"),
                           evidence.get("longer_chains"))
            every = _given_rungs(store, campaign_id, str(law), evidence, policy)
            if every is not None:
                rungs = every.pop(EMPTY)
            starts_reading = evidence.get("starts_reading") if every is not None else None
            graphs_to_n = (_graphs_to_n(store, campaign_id, str(law)) if evidence.get("evidence_failed") else None)
            inputs = decision_inputs(str(law), rungs, policy, failed_seeds=evidence.get("failed_seeds"),
                                     failed_analyses=evidence.get("failed_analyses"),
                                     standing=evidence.get("standing"), deep_lane_in_flight=dict(lanes),
                                     gate=gate, chains=every, starts_reading=starts_reading,
                                     evidence_failed=evidence.get("evidence_failed"), graphs_to_n=graphs_to_n,
                                     learned=learned)
            context = {"lane_occupancy": {str(n): c for n, c in lanes.items()},
                       "queue_depth": queue_at_start + enqueued, "pass_position": position,
                       "pass_size": len(order), "competing_for_lanes": competing,
                       "rank_among_competitors": (again.index(law) if law in again else None)}
            context_of_the_rules = dict(failed_seeds=evidence.get("failed_seeds"),
                                        failed_analyses=evidence.get("failed_analyses"),
                                        standing=evidence.get("standing"), deep_lane_in_flight=lanes, gate=gate,
                                        **({"evidence_failed": evidence["evidence_failed"],
                                            **({"graphs_to_n": graphs_to_n} if graphs_to_n else {})}
                                           if evidence.get("evidence_failed") else {}))
            decision = (decide_every_chain(str(law), {EMPTY: rungs, **every}, policy, starts_reading=starts_reading,
                                           **context_of_the_rules)
                        if every is not None else decide(str(law), rungs, policy, **context_of_the_rules))
            if str(law) in by_word:
                inputs["run_on"] = by_word[str(law)]
                decision = run_on(decision, by_word[str(law)], policy)
            if str(law) in ceilings:
                inputs["memory_ceiling"] = ceilings[str(law)]
                decision = memory_settle(decision, ceilings[str(law)], policy)
            if decision.action == RUN_NEXT and lanes.get(decision.next_n) is not None:
                lanes[decision.next_n] += 1
            if decision.action == RUN_NEXT and decision.rule == "gate_audit":
                gate["audit_in_flight"] = int(gate.get("audit_in_flight") or 0) + 1
            if decision.action == RUN_NEXT and decision.rule == "plateau_follow":
                gate["plateau_follow_laws"] = sorted(set(gate.get("plateau_follow_laws") or []) | {str(law)})
            if evidence.get("phenotype") is not None:
                store.record_phenotype(campaign_id, str(law), evidence["phenotype"])
            effect = _apply_and_record(store, campaign_id, decision, policy,
                                       {"released_hold": False, "inputs": inputs, "context": context},
                                       parked_ok=str(law) in parked_redo)
            enqueued += int(effect.get("jobs_created") or 0)
            (redo or set()).discard(str(law))
            if effect.get("refused") is not None:
                if decision.action == RUN_NEXT and lanes.get(decision.next_n) is not None:
                    lanes[decision.next_n] -= 1
                tally[("refused", str(effect["refused"]))] += 1
            else:
                tally[(decision.action, decision.rule)] += 1
            if redo and (position + 1) % REDO_KEPT_EVERY == 0:
                _keep_redo(store, campaign_id, rules, redo)
        except Exception as error:
            said = failure_text(error)
            reporter = getattr(store, "record_failure", None)
            if reporter is not None:
                reporter(campaign_id, str(law), said)
            tally[("failed", type(error).__name__)] += 1
            if not transient(error):
                counter = getattr(store, "count_failure", None)
                if callable(counter):
                    counter(campaign_id, str(law), said)
                undecidable = getattr(store, "undecidable", None)
                why = undecidable(campaign_id, str(law)) if callable(undecidable) else None
                if why:
                    _stop_undecidable(store, campaign_id, str(law), policy, why, tally)
    policy = base_policy
    if redo is not None and not redo:
        writer(campaign_id, rules)
    elif redo:
        _keep_redo(store, campaign_id, rules, redo)
    if store.queue_depth(campaign_id) == 0:
        held = sorted((h for h in store.held_laws(campaign_id) or []
                       if int(h.get("next_n") or 0) < policy.plateau_from_n),
                      key=lambda h: (h.get("priority") or 9, h.get("since") or ""))
        for entry in held[:hold_release_limit]:
            decision = Decision(law=str(entry["law"]), action=RUN_NEXT, rule="hold_released",
                                reason="nothing else was waiting", at_n=entry.get("at_n"),
                                next_n=entry.get("next_n"), priority=None,
                                facts={"held_since": entry.get("since")})
            effect = _apply_and_record(store, campaign_id, decision, policy,
                                       {"released_hold": True, "inputs": None,
                                        "context": {"queue_depth": 0, "released_of": len(held)}},
                                       released=True)
            tally[(decision.action, decision.rule) if effect.get("refused") is None
                  else ("refused", str(effect["refused"]))] += 1
    return tally
