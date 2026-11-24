from __future__ import annotations

import functools
import hashlib
import math
from dataclasses import asdict, dataclass, field, fields

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import structure_gate as SG

ENGINE_VERSION = "decision-engine-2"
SETTLING_RULES = frozenset({"d_s_settled"})
PARKING_RULES = frozenset({"reading_lost", "no_diffusive_window", "unsettled_twice", "no_reading", "no_second_rung",
                           "starts_alike", "starts_apart_twice",
                           "starts_apart_by_history", "not_promising",
                           "starts_shape_unread", "nothing_read", "repeats_a_known_result", "kept_shape",
                           "no_steady_chain", "over_budget", "cut"})
RULES_REVISION = 782
PROBES = ("d_s", "d_V", "d_B", "d_w")

RUN_NEXT, HOLD, STOP, DONE = "run_next", "hold", "stop", "done"
BUDGET_TERMINATION = "budget"
OVER_BUDGET = "over_budget"


@dataclass(frozen=True)
class Policy:
    base_sizes: tuple = (64, 256, 1024, 4096)
    deep_sizes: tuple = (16384, 65536, 262144, 1048576)
    seeds: int = 3
    empty_mean_degree: float = 0.05
    empty_from_n: int = 256
    connectivity_floor: float = 0.5
    connectivity_from_n: int = 1024
    dense_cap: float = 16.0
    dense_from_n: int = 256
    fact_sizes_in_a_row: int = 0
    audit_fraction: float = 0.10
    salt_shares: tuple = ()
    d_s_sigmas: float = 2.0
    mean_degree_tolerance: float = 0.03
    plateau_from_n: int = 262144
    deep_lane_laws: int = 4
    deep_lane_widths: tuple = ((1048576, 4),)
    work_budgets: tuple = ((64, 400000000000), (256, 400000000000), (1024, 400000000000), (4096, 400000000000),
                           (16384, 2000000000000), (65536, 24000000000000), (262144, 96000000000000),
                           (1048576, 290000000000000))
    work_unit: tuple = (("moves", 241), ("evaluations", 1889), ("changes", 0), ("lists", 10), ("entries", 19),
                        ("tests", 39))
    seconds_a_unit: float = 1.5e-10
    unsettled_rungs_to_park: int = 2
    second_rung: bool = True
    structure_gate: bool = True
    gap_exponent_at_most: float = -0.3752
    diameter_exponent_at_least: float = 0.1751
    gap_window: tuple = (4096, 65536)
    diameter_window: tuple = (4096, 262144)
    giant_fraction_at_least: float = 0.5
    gap_exponent_at_least: float = -2.2
    diameter_exponent_at_most: float = 1.1
    gap_opens_above: float = 0.2
    diameter_shrinks_below: float = -0.05
    gate_at_n: int = 65536
    early_gate_at_n: int = 16384
    early_gap_exponent_above: float = -0.2
    early_diameter_exponent_below: float = 0.13
    early_gate_agreements: int = 100
    gate_audit_gap_margin: float = 0.1
    gate_audit_diameter_margin: float = 0.05
    gate_audit_in_flight: int = 4
    plateau_follow_steps: int = 3
    plateau_follow_in_flight: int = 1
    every_chain: bool = False
    depth_rules: int = 0
    promising_from_n: int = 262144
    promising_bar: bool = True
    merit_budget_scale: float = 2.0
    deep_salt_at_most: float = 0.005
    finite_size_fits: tuple = ()
    finite_size_scatter_sigmas: float = 2.0
    dimension_extends: bool = False
    nothing_read_gate: bool = True
    nothing_read_from_n: int = 64
    let_through_rule: str = ""
    let_through_from: int = 4096
    confirm_after: int = 100
    known_result_after: int = 0
    known_result_from: int = 0
    one_die: bool = False
    ab_share: float = 0.0
    gate_shares: tuple = ()
    gate_from: tuple = ()
    kept_shape_park: bool = False
    known_results: tuple = ()
    steady_chain_gate: bool = False
    nothing_read_piece_share: float = 0.0
    cut_gate: bool = False
    longer_chain_budget_scale: float = 1.0
    ledger_counts_priced: bool = False
    learn_in_batches_of: int = 100
    first_multipliers: tuple = ()
    spec_decides: str = ""

    @classmethod
    def from_spec(cls, spec: dict) -> "Policy":
        block = in_today_s_fields((((spec or {}).get("engine") or {}).get("policy")) or {})
        known = {f.name for f in fields(cls)} - {"spec_decides", "first_multipliers"}
        unknown = sorted(set(block) - known)
        if unknown:
            raise ValueError(f"engine.policy declares fields the engine does not have: {unknown}")
        freeze = lambda v: tuple(freeze(x) for x in v) if isinstance(v, (list, tuple)) else v
        return cls(**{key: freeze(value) for key, value in block.items()}, spec_decides=spec_decides(spec),
                   first_multipliers=first_multipliers_of(spec))

    def first_multiplier(self, n: int) -> int:
        return int(dict(self.first_multipliers).get(int(n), 1))

    def ladder(self) -> tuple:
        return tuple(self.base_sizes) + tuple(self.deep_sizes)

    def salt_share(self, gate: str, n) -> float:
        if self.let_through_rule:
            return self.live_share(gate, n)
        share = float(self.audit_fraction)
        for name, below, deep in self.salt_shares:
            if name == gate:
                share = float(deep if n is not None and int(n) >= G.SALT_DEEP_FROM else below)
                break
        if n is None:
            return share
        following = next((m for m in self.ladder() if int(m) > int(n)), None)
        if following is not None and int(following) >= int(self.promising_from_n) and self.promising_bar:
            return 0.0
        return min(share, float(self.deep_salt_at_most)) if int(n) >= G.SALT_DEEP_FROM else share

    def known_result_size(self) -> int:
        return int(self.known_result_from or self.let_through_from)

    def own_share(self, gate: str) -> float | None:
        return next((float(share) for name, share in self.gate_shares if G.today(name) == G.today(gate)), None)

    def asks_for(self, gate: str) -> bool:
        return bool(self.cut_gate) if G.today(gate) == "cut" else True

    def acts_from(self, gate: str) -> int:
        return next((int(n) for name, n in self.gate_from if G.today(name) == G.today(gate)), 0)

    def live_share(self, gate: str, n) -> float:
        if n is None or int(n) < int(self.let_through_from) or int(n) < self.acts_from(gate):
            return G.RECORD_ONLY
        if not self.asks_for(gate):
            return G.RECORD_ONLY
        if self.own_share(gate) is not None:
            return self.own_share(gate)
        if self.ab_share:
            return float(self.ab_share)
        for row in self.salt_shares:
            if len(row) == 3 and G.today(row[0]) == G.today(gate) and int(row[1]) == int(n):
                return float(row[2])
        return G.TESTING_SHARE

    def in_the_b_arm(self, n) -> bool:
        return bool(self.ab_share) and n is not None and int(n) >= int(self.let_through_from)

    def let_through(self, law: str, gate: str, n) -> bool:
        if self.let_through_rule:
            return G.drawn(law, gate, None if self.in_the_b_arm(n) else n, self.live_share(gate, n),
                           one_die=bool(self.one_die))
        return G.salted(law, gate, self.salt_share(gate, n))

    def deep_lane_width(self, n: int) -> int:
        return int(dict(self.deep_lane_widths).get(int(n), self.deep_lane_laws))

    def lane_rungs(self) -> tuple:
        declared = tuple(int(n) for n, _ in self.deep_lane_widths)
        last = self.ladder()[-1]
        if last in declared:
            return declared
        if int(last) < int(self.plateau_from_n):
            return declared
        return declared + (last,)

    def work_budget(self, n: int) -> int:
        table = {int(size): int(units) for size, units in self.work_budgets}
        if not table:
            raise ValueError("engine.policy.work_budgets gives no size a budget in work")
        if int(n) in table:
            return table[int(n)]
        top = max(table)
        steps = max(0, round(math.log(int(n) / top, 4)))
        return table[top] * 4 ** steps

    def work_weights(self) -> dict:
        return {str(name): int(weight) for name, weight in self.work_unit}


@dataclass(frozen=True)
class Seed:
    termination: str | None = None
    given_at_cap: bool = False
    work_units: int | None = None
    moves: int | None = None
    first_chunk_units: int | None = None
    first_chunk_moves: int | None = None
    first_multiplier: int | None = None
    final_multiplier: int | None = None
    work_budget: int | None = None


@dataclass(frozen=True)
class Rung:
    n: int
    mean_degree: float | None
    connected_fraction: float | None = None
    probes: dict = field(default_factory=dict)
    chains_disagreed: bool = False
    seeds_measured: int = 3
    seeds: tuple = ()
    structure: dict = field(default_factory=dict)
    d_s_refusal: str | None = None
    longer_chain: bool = False
    measured_se: dict = field(default_factory=dict)
    small_world_fraction: float | None = None
    valid_fractions: dict = field(default_factory=dict)
    giant_mean_degree: float | None = None


@dataclass(frozen=True)
class Decision:
    law: str
    action: str
    rule: str
    reason: str
    at_n: int | None
    next_n: int | None
    priority: int | None = None
    facts: dict = field(default_factory=dict)
    observations: tuple = ()
    engine: str = ENGINE_VERSION

    def as_dict(self) -> dict:
        out = asdict(self)
        out["observations"] = list(self.observations)
        return out


def first_multipliers_of(spec: dict | None) -> tuple:
    declared = ((spec or {}).get("policy") or {}).get("initial_sweeps_multiplier")
    if not isinstance(declared, dict):
        return ()
    out = []
    for n, value in declared.items():
        if isinstance(value, bool) or not isinstance(value, int) or not str(n).isdigit():
            continue
        out.append((int(n), max(1, int(value))))
    return tuple(sorted(out))


def is_engine_campaign(spec: dict) -> bool:
    return (((spec or {}).get("engine") or {}).get("contract")) == ENGINE_VERSION


LIVE_FIELDS = ("salt_shares", "known_results")
FORMER_FIELDS = {"seen_enough_after": "known_result_after", "seen_enough_from": "known_result_from",
                 "seen_signatures": "known_results"}
FIELDS_BEFORE = {today: former for former, today in FORMER_FIELDS.items()}


def in_today_s_fields(block: dict) -> dict:
    return {FORMER_FIELDS.get(key, key): value for key, value in dict(block or {}).items()}
SET_FIELDS = (("fact_sizes_in_a_row", 0), ("one_die", False), ("nothing_read_piece_share", 0.0),
              ("cut_gate", False), ("longer_chain_budget_scale", 1.0), ("ledger_counts_priced", False))
SPEC_DECIDES_WHEN = ("hold_structure", "lattice_chains_meet")
SPEC_DECIDES_SAMPLING = ("required_consecutive_passes", "max_sweeps_multiplier", "given_starts", "given_start",
                         "given_start_by_law", "given_start_rule", "one_shot", "hold_structure",
                         "lattice_chains_meet")


def spec_decides(spec: dict | None) -> str:
    sampling = (spec or {}).get("sampling_contract") or {}
    if not any(key in sampling for key in SPEC_DECIDES_WHEN):
        return ""
    import json
    decides = {"sampling_contract": {key: sampling[key] for key in SPEC_DECIDES_SAMPLING if key in sampling},
               "policy": dict((spec or {}).get("policy") or {})}
    return json.dumps(decides, sort_keys=True, separators=(",", ":"), default=str)


def rules_revision(policy: Policy) -> int:
    return RULES_REVISION


def policy_fingerprint(policy: Policy) -> str:
    unset = {key for key, default in SET_FIELDS if getattr(policy, key) == default}
    items = {FIELDS_BEFORE.get(key, key): value for key, value in asdict(policy).items()
             if not (policy.let_through_rule and key in LIVE_FIELDS) and key not in unset}
    payload = "|".join([ENGINE_VERSION, str(rules_revision(policy))]
                       + [f"{key}={value!r}" for key, value in sorted(items.items())])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def in_audit_sample(law: str, fraction: float) -> bool:
    value = int(hashlib.sha256(str(law).encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return value < fraction


def _value(rung: Rung, probe: str):
    entry = rung.probes.get(probe)
    return entry[0] if entry else None


def d_s_pair(rungs: list):
    if not rungs or _value(rungs[-1], "d_s") is None:
        return None
    if len(rungs) >= 2 and _value(rungs[-2], "d_s") is not None:
        return rungs[-2], rungs[-1], None
    if len(rungs) >= 3 and _value(rungs[-2], "d_s") is None and _value(rungs[-3], "d_s") is not None:
        return rungs[-3], rungs[-1], int(rungs[-2].n)
    return None


def signals(rungs: list, policy: Policy) -> dict:
    top = rungs[-1]
    out = {"d_s_step": None, "d_s_sigma": None, "d_s_settled": False, "d_s_across": None,
           "mean_degree_step": None, "mean_degree_settled": False,
           "other_probes": [p for p in PROBES[1:] if _value(top, p) is not None],
           "connected_step": None, "connectivity_growing": False}
    if len(rungs) >= 2:
        prev = rungs[-2]
        if prev.connected_fraction is not None and top.connected_fraction is not None:
            out["connected_step"] = round(top.connected_fraction - prev.connected_fraction, 6)
            out["connectivity_growing"] = top.connected_fraction > prev.connected_fraction
    pair = d_s_pair(rungs)
    if pair is not None:
        a, b = pair[0].probes.get("d_s"), pair[1].probes.get("d_s")
        out["d_s_across"] = pair[2]
        if a and b and a[0] is not None and b[0] is not None:
            out["d_s_step"] = round(b[0] - a[0], 6)
            if a[1] is not None and b[1] is not None:
                sigma = math.hypot(a[1], b[1])
                out["d_s_sigma"] = round(sigma, 6)
                out["d_s_settled"] = abs(b[0] - a[0]) <= policy.d_s_sigmas * sigma
            out["d_s_settled_by"] = _settled_by(pair[0], pair[1], a[0], b[0], policy, out)
    if len(rungs) >= 2:
        prev = rungs[-2]
        if prev.mean_degree and top.mean_degree is not None:
            rel = abs(top.mean_degree - prev.mean_degree) / prev.mean_degree
            out["mean_degree_step"] = round(rel, 6)
            out["mean_degree_settled"] = rel <= policy.mean_degree_tolerance
    return out


def _measured(rung: Rung, probe: str = "d_s") -> float | None:
    value = (getattr(rung, "measured_se", None) or {}).get(probe)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def finite_size_fits(policy: Policy) -> dict | None:
    rows = tuple(policy.finite_size_fits or ())
    return _fits_document(rows, float(policy.finite_size_scatter_sigmas)) if rows else None


@functools.lru_cache(maxsize=8)
def _fits_document(rows: tuple, sigmas: float) -> dict:
    return {"families": {str(row[0]): {"d_inf": float(row[1]), "a": float(row[2]), "omega": float(row[3]),
                                       "scatter": float(row[4]), "n_min": int(row[5])} for row in rows},
            "scatter_sigmas": sigmas}


@functools.lru_cache(maxsize=1)
def _committed_fits() -> dict:
    from graph_scale_dynamics.calibration import finite_size
    return finite_size.committed()


def _settled_by(lo: Rung, hi: Rung, d_a: float, d_b: float, policy: Policy, out: dict) -> dict:
    err_a, err_b = _measured(lo), _measured(hi)
    if err_a is None or err_b is None:
        return {"rule": "se", "why": "no measured error at " + ("both rungs" if err_a is None and err_b is None
                                                                  else f"N={int((lo if err_a is None else hi).n):,}")}
    from graph_scale_dynamics.calibration import finite_size
    fits = finite_size_fits(policy)
    ok, judged = finite_size.settled(d_a, err_a, int(lo.n), d_b, err_b, int(hi.n), sigmas=float(policy.d_s_sigmas),
                                     fits=fits or _committed_fits())
    out["d_s_settled"] = bool(ok)
    return {"rule": "measured", "settled": bool(ok), "step": round(judged["step"], 6),
            "noise": round(judged["noise"], 6), "finite_size": round(judged["finite_size"], 6),
            "measured_se": [round(err_a, 6), round(err_b, 6)], "contract": judged["contract"],
            "fits": "the campaign's" if fits else "the committed file's"}


def budget_use(rung: Rung, policy: Policy) -> list:
    out = []
    for index, seed in enumerate(rung.seeds):
        budget = seed.work_budget if isinstance(seed.work_budget, int) and seed.work_budget > 0 else None
        units = seed.work_units if isinstance(seed.work_units, int) else None
        out.append({"seed": index, "work_units": units, "work_budget": budget,
                    "budget_fraction": (round(units / budget, 6) if units is not None and budget else None),
                    "termination": seed.termination, "reached": seed.termination == BUDGET_TERMINATION})
    return out


def _median(values: list) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def first_chunk_prediction(rungs, policy: Policy, next_n: int, *, same_size: bool = False,
                           multiplier: int | None = None, scale: float = 1.0) -> dict | None:
    ordered = sorted(rungs or (), key=lambda r: r.n)
    below = [rung for rung in ordered if (int(rung.n) == int(next_n) if same_size else int(rung.n) < int(next_n))]
    if not below:
        return None
    rung = below[-1]
    rows = [seed for seed in rung.seeds
            if isinstance(seed.first_chunk_units, int) and isinstance(seed.first_chunk_moves, int)
            and seed.first_chunk_moves > 0 and isinstance(seed.first_multiplier, int) and seed.first_multiplier > 0]
    if not rows:
        return None
    per_move = _median([seed.first_chunk_units / seed.first_chunk_moves for seed in rows])
    moves = _median([seed.first_chunk_moves / seed.first_multiplier for seed in rows])
    times = int(multiplier) if multiplier is not None else policy.first_multiplier(int(next_n))
    predicted = int(math.ceil(per_move * moves * times * int(next_n) / int(rung.n)))
    budget = int(math.floor(policy.work_budget(int(next_n)) * float(scale)))
    return {"from_n": int(rung.n), "seeds": len(rows), "units_a_move": round(per_move, 6),
            "multiplier": times, "predicted": predicted, "budget": budget, "fits": predicted <= budget}


def longer_chain_multiplier(rung: Rung, policy: Policy) -> int:
    ran = [int(seed.final_multiplier) for seed in rung.seeds if isinstance(seed.final_multiplier, int)]
    return 2 * max(1, max(ran + [policy.first_multiplier(int(rung.n))]))


def over_budget_reason(next_n: int, prediction: dict, rule: str, *, former: bool = False) -> str:
    tail = (f"more than the size's budget of {int(prediction['budget']):,}: parked as costing more than its "
            f"budget, with everything it measured kept ({rule})")
    if rule == "longer_chain" and int(prediction["from_n"]) == int(next_n) and not former:
        return (f"a longer chain at the size it is at, N={int(next_n):,}, {int(prediction['multiplier'])} times "
                f"the moves, is predicted at {int(prediction['predicted']):,} units of work from its own seeds at "
                f"that size, " + tail)
    return (f"its first chunk at N={int(next_n):,} is predicted at {int(prediction['predicted']):,} units of work "
            f"from its own seeds at N={int(prediction['from_n']):,}, " + tail)


def budget_gate(law: str, decision: "Decision", rungs, policy: Policy, scale: float = 1.0) -> "Decision":
    if decision.action != RUN_NEXT or decision.next_n is None or not policy.work_budgets or not rungs:
        return decision
    ordered = sorted(rungs, key=lambda r: r.n)
    top = ordered[-1]
    if int(decision.next_n) == int(top.n):
        if decision.rule != "longer_chain":
            return decision
        prediction = first_chunk_prediction(ordered, policy, int(decision.next_n), same_size=True,
                                            multiplier=longer_chain_multiplier(top, policy), scale=scale)
    else:
        prediction = first_chunk_prediction(ordered, policy, int(decision.next_n), scale=scale)
    if prediction is None:
        return decision
    facts = dict(decision.facts or {}, first_chunk=prediction)
    if prediction["fits"]:
        return Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason,
                        at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority, facts=facts,
                        observations=decision.observations)
    kept = {key: value for key, value in facts.items() if key != "lane"}
    return Decision(law=law, action=STOP, rule=OVER_BUDGET,
                    reason=over_budget_reason(int(decision.next_n), prediction, decision.rule),
                    at_n=decision.at_n, next_n=None, priority=None,
                    facts=dict(kept, refused={"action": decision.action, "rule": decision.rule,
                                              "next_n": int(decision.next_n), "priority": decision.priority}),
                    observations=decision.observations)


def decide(law: str, rungs, policy: Policy = Policy(), *, failed_seeds: dict | None = None,
           standing: dict | None = None, deep_lane_in_flight: int | None = None,
           failed_analyses: dict | None = None, gate: dict | None = None, evidence_failed: str | None = None,
           graphs_to_n: int | None = None, whole_law: bool = True) -> Decision:
    decision = _decide(law, rungs, policy, failed_seeds=failed_seeds, standing=standing,
                       deep_lane_in_flight=deep_lane_in_flight, failed_analyses=failed_analyses,
                       evidence_failed=evidence_failed, graphs_to_n=graphs_to_n)
    decision = _salt(law, policy, decision, deep_lane_in_flight, rungs=rungs)
    decision = _gate(law, sorted(rungs, key=lambda r: r.n), policy, decision, gate or {})
    if whole_law:
        from graph_scale_dynamics.decisions import depth
        ordered = sorted(rungs, key=lambda r: r.n)
        decision = depth.complete_budget(law, decision, ordered, policy)
        decision = depth.bar(law, decision, ordered, policy)
        from graph_scale_dynamics.decisions import cut, nothing_read
        decision = nothing_read.gate(law, decision, {"empty": ordered}, policy)
        decision = cut.gate(law, decision, ordered, policy)
        decision = budget_gate(law, decision, ordered, policy, depth.budget_scale(decision, policy))
    return _with_lane(decision, policy, standing)


LANE_MERIT, LANE_AUDIT, LANE_FAMILY = 0, 1, 2
LANE_ORDER = {LANE_MERIT: "bought on its own reading", LANE_AUDIT: "audit traffic",
              LANE_FAMILY: "a calibration family"}
AUDIT_RULES = frozenset(stream.rule for stream in G.STREAMS if stream.audit)


def is_audit_traffic(rule: str, facts: dict) -> bool:
    facts = facts or {}
    return bool(str(rule) in AUDIT_RULES or facts.get("salted") or (facts.get("gate") or {}).get("salted")
                or (facts.get("gate") or {}).get("follow"))


def _with_lane(decision: Decision, policy: Policy, standing: dict | None) -> Decision:
    if (decision.action not in (RUN_NEXT, HOLD) or decision.next_n is None
            or int(decision.next_n) not in policy.lane_rungs()):
        return decision
    facts = decision.facts or {}
    family = (standing or {}).get("control_family")
    audit = is_audit_traffic(decision.rule, facts)
    rank = LANE_FAMILY if family else (LANE_AUDIT if audit else LANE_MERIT)
    lane = {"rank": rank, "queue": LANE_ORDER[rank], "audit": audit, "family": family,
            "law_score": (standing or {}).get("law_score"),
            **({"tier": int(facts["dimension"]["tier"])} if (facts.get("dimension") or {}).get("tier") else {})}
    return Decision(law=decision.law, action=decision.action, rule=decision.rule, reason=decision.reason,
                    at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                    facts=dict(facts, lane=lane), observations=decision.observations)


def _spent(rungs: list, gate: str) -> dict:
    return {"gate": gate, "salted_at": int(rungs[-2].n), "held_at": int(rungs[-1].n)}


def _spent_text(spent: dict) -> str:
    return (f"salted past it at N={spent['salted_at']:,} and withheld by it again at N={spent['held_at']:,}: "
            "the salt's one rung is spent (537, B1)")


def _withheld_at_the_rung_below(law: str, rungs, policy: Policy, gate: str) -> dict | None:
    rungs = sorted(rungs or (), key=lambda r: r.n)
    if len(rungs) < 2:
        return None
    below = _decide(law, rungs[:-1], policy)
    if G.gate_of(below.rule) != str(gate):
        return None
    return _spent(rungs, gate)


def lane_in_flight(policy: Policy, n, deep_lane_in_flight=None):
    if n is None:
        return None
    if isinstance(deep_lane_in_flight, dict):
        if int(n) not in policy.lane_rungs():
            return None
        return deep_lane_in_flight.get(n)
    return deep_lane_in_flight if n in policy.lane_rungs() else None


def _salt(law: str, policy: Policy, decision: Decision, deep_lane_in_flight=None, *, rungs=()) -> Decision:
    if decision.rule not in G.WITHHOLDING_GATES or decision.action not in (HOLD, STOP):
        return decision
    share = policy.salt_share(decision.rule, decision.at_n)
    if not policy.let_through(law, decision.rule, decision.at_n):
        return decision
    spent = None if policy.let_through_rule else _withheld_at_the_rung_below(law, rungs, policy, decision.rule)
    if spent is not None:
        return Decision(law=law, action=decision.action, rule=decision.rule,
                        reason=f"{decision.reason}; {_spent_text(spent)}", at_n=decision.at_n,
                        next_n=decision.next_n, priority=decision.priority,
                        facts=dict(decision.facts, salt_spent=spent), observations=decision.observations)
    next_n = (decision.next_n if decision.action == HOLD else
              next((n for n in policy.ladder() if decision.at_n is not None and n > int(decision.at_n)), None))
    if next_n is None:
        return decision
    salted = list(decision.facts.get("salted") or []) + [decision.rule]
    facts = dict(decision.facts, salted=salted, salted_from={"rule": decision.rule, "reason": decision.reason})
    in_flight = lane_in_flight(policy, next_n, deep_lane_in_flight)
    if in_flight is not None and in_flight >= policy.deep_lane_width(next_n):
        return Decision(law=law, action=HOLD, rule="deep_lane_full",
                        reason=(f"salted past {decision.rule}, and N={next_n} has {in_flight} laws in flight, the "
                                "most it takes at once; this law waits, best law score first"),
                        at_n=decision.at_n, next_n=next_n, priority=None, facts=facts,
                        observations=decision.observations)
    return Decision(law=law, action=RUN_NEXT, rule="salted",
                    reason=(f"{let_through_text(decision.rule, share, policy)}; {decision.rule}: {decision.reason}"),
                    at_n=decision.at_n, next_n=next_n, priority=2, facts=facts,
                    observations=decision.observations)


def let_through_text(gate: str, share: float, policy: Policy) -> str:
    if not policy.let_through_rule:
        return (f"salted past {gate}: {share:.0%} of the laws it would withhold a rung from have it, fixed by "
                "identity, so what the gate costs is measured")
    if share >= 1.0 and policy.own_share(gate) is not None:
        return (f"let through past {gate}: the study's design records this gate and holds no law back by it, so "
                "every verdict it would give is checked one size up")
    if share >= 1.0:
        return (f"let through past {gate}: below N={int(policy.let_through_from):,} every verdict is recorded and "
                "every law goes on, so each verdict is checked one size up")
    if policy.ab_share:
        return (f"let through past {gate}: in its B arm, {share:.0%} of the laws drawn once for the gate, which it never "
                "holds back, so what it would have held back is measured")
    return (f"let through past {gate}: {share:.0%} of the laws it would withhold go one size on, drawn a size at a "
            "time, so whether the gate holds is counted")


def _in_a_row(rungs: list, policy: Policy) -> list | None:
    k = int(policy.fact_sizes_in_a_row or 0)
    if k <= 1:
        return None
    return list(rungs[-k:]) if len(rungs) >= k else []


def _sizes_text(row: list) -> str:
    sizes = [f"{int(r.n):,}" for r in row]
    return f"N={', '.join(sizes[:-1])} and {sizes[-1]}"


def _empty(rungs: list, policy: Policy) -> str | None:
    top = rungs[-1]
    row = _in_a_row(rungs, policy)
    if row is None:
        if top.n >= policy.empty_from_n and all((r.mean_degree or 0.0) <= policy.empty_mean_degree for r in rungs):
            return f"mean degree at most {policy.empty_mean_degree} at every rung through N={top.n}"
        return None
    degrees = [r.mean_degree or 0.0 for r in row]
    if top.n < policy.empty_from_n or not row or any(d > policy.empty_mean_degree for d in degrees):
        return None
    if degrees[-1] > degrees[0] and degrees[-1] >= max(degrees):
        return None
    return (f"mean degree at most {policy.empty_mean_degree} at {_sizes_text(row)}, {len(row)} sizes in a row, "
            "and not rising")


def _disconnected(rungs: list, policy: Policy) -> str | None:
    top = rungs[-1]
    if (top.n < policy.connectivity_from_n or top.connected_fraction is None
            or top.connected_fraction >= policy.connectivity_floor):
        return None
    row = _in_a_row(rungs, policy)
    if row is not None and (not row or any(r.connected_fraction is None
                                           or r.connected_fraction >= policy.connectivity_floor for r in row)):
        return None
    trend = signals(rungs, policy) if len(rungs) >= 2 else {}
    if trend.get("connectivity_growing"):
        return None
    step = trend.get("connected_step")
    moved = "" if step is None else f", {step:+.3f} from the rung below"
    if row is not None:
        return (f"largest component under {policy.connectivity_floor} of the graph at {_sizes_text(row)}, "
                f"{len(row)} sizes in a row, {top.connected_fraction:.3f} at N={top.n} and not growing{moved}")
    return (f"largest component {top.connected_fraction:.3f} of the graph at N={top.n}, under "
            f"{policy.connectivity_floor} and not growing{moved}")


def _too_dense(rungs: list, policy: Policy) -> str | None:
    top = rungs[-1]
    row = _in_a_row(rungs, policy)
    if row is None:
        if top.n >= policy.dense_from_n and top.mean_degree is not None and top.mean_degree >= policy.dense_cap:
            return f"mean degree {top.mean_degree:.2f} at N={top.n}, at the cap of {policy.dense_cap:g}"
        return None
    if top.n < policy.dense_from_n or not row or any(r.mean_degree is None or r.mean_degree < policy.dense_cap
                                                       for r in row):
        return None
    return (f"mean degree at the cap of {policy.dense_cap:g} at {_sizes_text(row)}, {len(row)} sizes in a row, "
            f"{top.mean_degree:.2f} at N={top.n}")


FINAL_VERDICTS = (("empty", _empty), ("disconnected", _disconnected), ("too_dense", _too_dense))


def _settled_steps(rungs: list, policy: Policy) -> int:
    steps, end = 0, len(rungs)
    while end >= 2 and int(rungs[end - 1].n) >= int(policy.base_sizes[-1]):
        found = signals(rungs[:end], policy)
        if not found["d_s_settled"]:
            break
        steps += 1
        end -= 2 if found["d_s_across"] else 1
    return steps


GATE_RULES = frozenset({"no_finite_dimension", "no_giant_component", "gate_audit", "plateau_follow"})
GATED_RULES = frozenset({"d_s_settled", "salted", "unsettled", "no_plateau", "deep_lane_full", "second_rung",
                         "starts_shape", "starts_apart", "dimension_shows"})
_UNDECIDED = (SG.SPLIT, SG.UNDECIDABLE)


def _with_gate(decision: Decision, gate_facts: dict) -> Decision:
    return Decision(law=decision.law, action=decision.action, rule=decision.rule, reason=decision.reason,
                    at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                    facts=dict(decision.facts, gate=gate_facts), observations=decision.observations)


def _chain_facts(reading: dict) -> dict:
    keep = ("finite_dimension", "code", "exponents", "implied_spectral_dimension", "implied_fractal_dimension",
            "why")
    return {key: reading.get(key) for key in keep if key in reading}


def _exponents_text(chains: dict) -> str:
    def one(name, reading):
        e = (reading or {}).get("exponents") or {}
        gap, diameter = e.get("gap"), e.get("diameter")
        if gap is None or diameter is None:
            return f"{name}: {(reading or {}).get('code') or 'not read'}"
        return f"{name}: gap {gap:+.3f}, diameter {diameter:+.3f}"
    return "; ".join(one(label, chains.get(chain)) for chain, label in (("empty", "empty"), ("given", "given")))


def _gate(law: str, rungs: list, policy: Policy, decision: Decision, context: dict) -> Decision:
    if (not policy.structure_gate or decision.rule not in GATED_RULES or decision.next_n is None or not rungs
            or not any(getattr(rung, "structure", None) for rung in rungs)):
        return decision
    top = int(rungs[-1].n)
    if top < int(policy.early_gate_at_n):
        return decision
    t = SG.thresholds_of(policy)
    underlying = {"action": decision.action, "rule": decision.rule, "next_n": decision.next_n,
                  "reason": decision.reason}
    facts = {"contract": SG.GATE_CONTRACT, "at_n": top, "underlying": underlying}
    if not SG.has_census(rungs):
        return _with_gate(decision, dict(facts, result="not read",
                                         why="no rung carries a structure census on either chain"))
    if top < int(policy.gate_at_n):
        return _early_stage(law, rungs, policy, decision, context, t, facts)
    reading = SG.read_chains(rungs, t)
    facts.update(stage="full", result=reading["result"],
                 chains={chain: _chain_facts(reading["chains"][chain]) for chain in SG.CHAINS},
                 log_diameter=reading["log_diameter"])
    if top == int(policy.gate_at_n):
        early = SG.early_clear_case(rungs, policy, t)
        facts["early"] = {"would_refuse": early["would_refuse"],
                          "agrees": bool(early["would_refuse"] and reading["result"] == SG.NOT_FINITE),
                          "disagrees": bool(early["would_refuse"] and reading["result"] == SG.FINITE)}
    if reading["result"] == SG.FINITE:
        return _with_gate(decision, facts)
    if reading["no_giant_component"]:
        from_empty = reading["chains"]["empty"]
        dropped = ((from_empty.get("exponents") or {}).get("rungs_below_giant_floor")) or []
        reason = (f"structure gate at N={top:,}: the giant component of the chain from empty is under "
                  f"{policy.giant_fraction_at_least:.0%} of the graph at the rungs the rule needs (below it: "
                  + ", ".join(f"{int(n):,}" for n in dropped) + "); fragmented, so no dimension is read (3c)")
        return _refuse_or_audit(law, policy, decision, facts, reason=reason, near=False, context=context,
                                rule="no_giant_component", rungs=rungs)
    if reading["result"] in _UNDECIDED:
        earlier = [rung for rung in rungs if rung.n < top]
        before = (SG.read_chains(earlier, t) if earlier and int(earlier[-1].n) >= int(policy.gate_at_n) else None)
        why = "; ".join(f"{label}: {reading['codes'][chain]}" for chain, label in (("empty", "empty"),
                                                                                  ("given", "given"))
                        if chain in reading["codes"])
        if before is None or before["result"] not in _UNDECIDED:
            facts["one_more_rung"] = {"why": why or "the chains disagree on structure"}
            return _with_gate(decision, facts)
        twice = ("chains disagree on structure, twice" if reading["result"] == SG.SPLIT == before["result"]
                 else "undecidable twice")
        facts["twice"] = {"at_n": [int(earlier[-1].n), top], "results": [before["result"], reading["result"]],
                          "codes": [before["codes"], reading["codes"]]}
        reason = (f"structure gate at N={top:,}: {twice}, at N={int(earlier[-1].n):,} and N={top:,} "
                  f"({why or _exponents_text(reading['chains'])}); refused (3c)")
        return _refuse_or_audit(law, policy, decision, facts, reason=reason,
                                near=SG.near_threshold(reading, policy), context=context, rungs=rungs)
    reason = (f"structure gate at N={top:,}: no finite dimension on either chain "
              f"({_exponents_text(reading['chains'])}; a finite dimension needs gap <= "
              f"{policy.gap_exponent_at_most} and diameter >= {policy.diameter_exponent_at_least})")
    return _refuse_or_audit(law, policy, decision, facts, reason=reason,
                            near=SG.near_threshold(reading, policy), context=context, rungs=rungs)


def _early_stage(law: str, rungs: list, policy: Policy, decision: Decision, context: dict, t: dict,
                 facts: dict) -> Decision:
    early = SG.early_clear_case(rungs, policy, t)
    switch = bool(context.get("early_stage_switch"))
    agreements = int(context.get("early_agreements") or 0)
    acting = switch and agreements >= int(policy.early_gate_agreements)
    facts.update(stage="early", result=("would refuse" if early["would_refuse"] else "not a clear case"),
                 early=early, acting=acting,
                 switch={"on": switch, "agreements": agreements, "needed": int(policy.early_gate_agreements)})
    if not (early["would_refuse"] and acting):
        return _with_gate(decision, facts)
    reason = (f"structure gate at N={int(rungs[-1].n):,}, the clear case (its switch is on and "
              f"{agreements} shadow refusals agreed with the full rule): a gap not closing and a diameter "
              f"barely growing on both chains ({_exponents_text(early['chains'])}; limits: gap above "
              f"{policy.early_gap_exponent_above}, diameter below {policy.early_diameter_exponent_below})")
    return _refuse_or_audit(law, policy, decision, facts, reason=reason, near=SG.near_threshold(early, policy),
                            context=context, rungs=rungs)


def _refuse_or_audit(law: str, policy: Policy, decision: Decision, facts: dict, *, reason: str, near: bool,
                     context: dict, rule: str = "no_finite_dimension", rungs: list = ()) -> Decision:
    salted = policy.let_through(law, rule, decision.at_n)
    in_flight = int(context.get("audit_in_flight") or 0)
    followed = [str(other) for other in (context.get("plateau_follow_laws") or []) if str(other) != str(law)]
    inside = decision.next_n is not None and int(decision.next_n) <= max(int(policy.gap_window[1]),
                                                                         int(policy.diameter_window[1]))
    steps = _settled_steps(list(rungs), policy) if rungs else 0
    buys = decision.action == RUN_NEXT
    audit = {"salted": salted, "near_threshold": bool(near), "inside_the_windows": inside,
             "in_flight": in_flight, "limit": int(policy.gate_audit_in_flight), "plateau_steps": steps,
             "plateau_follow_in_flight": len(followed), "plateau_follow_limit": int(policy.plateau_follow_in_flight)}
    refused = dict(facts, refused=True, audit=audit)
    if context.get(_PLAIN):
        return Decision(law=law, action=STOP, rule=rule, reason=reason, at_n=decision.at_n, next_n=None,
                        facts=dict(decision.facts, gate=refused), observations=decision.observations)
    spent = (_refused_at_the_rung_below(law, rungs, policy, context, rule)
             if salted and not policy.let_through_rule else None)
    if spent is not None:
        return Decision(law=law, action=STOP, rule=rule, reason=f"{reason}; {_spent_text(spent)}",
                        at_n=decision.at_n, next_n=None, priority=None,
                        facts=dict(decision.facts, gate=dict(refused, salted=True, salt_spent=spent),
                                   salt_spent=spent),
                        observations=decision.observations)
    if salted:
        return Decision(law=law, action=decision.action, rule=decision.rule,
                        reason=f"{decision.reason}; salted past the structure gate, which would refuse: {reason}",
                        at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                        facts=dict(decision.facts, gate=dict(refused, salted=True),
                                   salted=list(decision.facts.get("salted") or []) + [rule]),
                        observations=decision.observations)
    audit_due = buys and inside and bool(near)
    follow_due = buys and steps >= int(policy.plateau_follow_steps)
    if audit_due and in_flight < int(policy.gate_audit_in_flight):
        return Decision(law=law, action=RUN_NEXT, rule="gate_audit",
                        reason=(f"gate audit (within the audit's margin of a threshold): {reason}; bought anyway, "
                                "inside the windows the gate reads, so a misread is caught"),
                        at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                        facts=dict(decision.facts, gate=refused), observations=decision.observations)
    if follow_due and len(followed) < int(policy.plateau_follow_in_flight):
        return Decision(law=law, action=RUN_NEXT, rule="plateau_follow",
                        reason=(f"plateau follow: d_s settled at {steps} steps in a row; {reason}; followed, so a "
                                "d_s that holds and then breaks past the gate's windows is seen"),
                        at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                        facts=dict(decision.facts, gate=dict(refused, follow=True)),
                        observations=decision.observations)
    if audit_due:
        audit["full"] = True
    if follow_due:
        audit["follow_full"] = True
    return Decision(law=law, action=STOP, rule=rule, reason=reason, at_n=decision.at_n, next_n=None,
                    priority=None, facts=dict(decision.facts, gate=refused), observations=decision.observations)


_PLAIN = "_plain"


def _refused_at_the_rung_below(law: str, rungs, policy: Policy, context: dict, rule: str) -> dict | None:
    rungs = sorted(rungs or (), key=lambda r: r.n)
    if len(rungs) < 2:
        return None
    probe = Decision(law=law, action=RUN_NEXT, rule="d_s_settled", reason="the rung below, read again",
                     at_n=int(rungs[-2].n), next_n=int(rungs[-1].n))
    below = _gate(law, rungs[:-1], policy, probe, dict(context or {}, **{_PLAIN: True}))
    if below.action != STOP or below.rule != str(rule):
        return None
    return _spent(rungs, rule)


def _decide(law: str, rungs, policy: Policy = Policy(), *, failed_seeds: dict | None = None,
            standing: dict | None = None, deep_lane_in_flight: int | None = None,
            failed_analyses: dict | None = None, evidence_failed: str | None = None,
            graphs_to_n: int | None = None) -> Decision:
    rungs = sorted(rungs, key=lambda r: r.n)
    ladder = policy.ladder()
    notes = ()

    def make(action, rule, reason, next_n=None, priority=None, facts=None):
        return Decision(law=law, action=action, rule=rule, reason=reason,
                        at_n=(rungs[-1].n if rungs else None), next_n=next_n,
                        priority=priority, facts=facts or {}, observations=notes)

    failed = {int(n): int(k) for n, k in (failed_seeds or {}).items() if int(k) > 0}
    if failed:
        n = max(failed)
        return Decision(law=law, action=STOP, rule="failed",
                        reason=f"{failed[n]} seed(s) at N={n} failed for good; the rung cannot be completed",
                        at_n=n, next_n=None, facts={"failed_seeds": failed}, observations=notes)
    unanalysed = {int(n): int(k) for n, k in (failed_analyses or {}).items() if int(k) > 0}
    if unanalysed:
        n = max(unanalysed)
        return Decision(law=law, action=STOP, rule="failed",
                        reason=f"{unanalysed[n]} seed(s) at N={n} could not be analysed; the rung cannot be completed",
                        at_n=n, next_n=None, facts={"failed_analyses": unanalysed}, observations=notes)
    if evidence_failed:
        top_n = max([int(r.n) for r in rungs] + ([int(graphs_to_n)] if graphs_to_n else []), default=None)
        return Decision(law=law, action=STOP, rule="failed",
                        reason=(f"the law's evidence cannot be read ({str(evidence_failed)[:300]}); no rung can be "
                                "decided"),
                        at_n=top_n, next_n=None, facts={"evidence_failed": str(evidence_failed)[:500]},
                        observations=notes)
    if not rungs:
        return make(RUN_NEXT, "start", "no rung measured yet", next_n=ladder[0])
    top = rungs[-1]
    facts = {"mean_degree": top.mean_degree, "connected_fraction": top.connected_fraction}
    facts["budget_use"] = budget_use(top, policy)
    if top.seeds_measured < policy.seeds:
        return make(RUN_NEXT, "complete_rung",
                    f"N={top.n} has {top.seeds_measured} of {policy.seeds} seeds", next_n=top.n, facts=facts)
    reached = [u for u in facts["budget_use"] if u["reached"]]
    if reached:
        facts["budget_ended"] = {"seeds": [u["seed"] for u in reached], "of": len(top.seeds), "at_n": int(top.n)}
    salted = []
    for gate, verdict in FINAL_VERDICTS:
        why = verdict(rungs, policy)
        if why is None:
            continue
        if not policy.let_through(law, gate, top.n):
            return make(STOP, gate, why, facts=facts)
        if not policy.let_through_rule and len(rungs) >= 2 and verdict(rungs[:-1], policy) is not None:
            spent = _spent(rungs, gate)
            return make(STOP, gate, f"{why}; {_spent_text(spent)}", facts=dict(facts, salt_spent=spent))
        salted.append(gate)
    if salted:
        facts["salted"] = salted
    facts["chains_disagreed_at"] = [r.n for r in rungs if r.chains_disagreed]
    following = next((n for n in ladder if n > top.n), None)
    if top.n < policy.base_sizes[-1]:
        return make(RUN_NEXT, "base_block", f"the base block runs to N={policy.base_sizes[-1]}",
                    next_n=following, facts=facts)
    if following is None:
        return make(DONE, "ladder_complete", f"N={top.n} is the last declared rung", facts=facts)
    found = signals(rungs, policy)
    facts.update(found)
    if found["mean_degree_settled"]:
        degree_part = "mean degree settled"
    elif found["mean_degree_step"] is None:
        degree_part = "mean degree has no step"
    else:
        degree_part = f"mean degree moved more than {policy.mean_degree_tolerance:.0%}"
    if found["d_s_settled"]:
        if following >= policy.plateau_from_n:
            head = rungs[:-2] if found.get("d_s_across") else rungs[:-1]
            before = signals(head, policy) if len(head) >= 2 else {"d_s_settled": False}
            facts["plateau"] = {"d_s_settled_before": bool(before["d_s_settled"])}
            missing = [] if before["d_s_settled"] else ["d_s did not settle at the step before"]
            if missing:
                return make(HOLD, "no_plateau", f"N={following} takes a plateau: " + "; ".join(missing),
                            next_n=following, facts=facts)
            in_flight = lane_in_flight(policy, following, deep_lane_in_flight)
            if in_flight is not None and in_flight >= policy.deep_lane_width(following):
                return make(HOLD, "deep_lane_full", f"N={following} has {in_flight} laws in flight, "
                            f"the most it takes at once; this law waits, best law score first",
                            next_n=following, facts=facts)
        return make(RUN_NEXT, "d_s_settled", f"d_s settled at the last step; {degree_part}",
                    next_n=following, priority=1, facts=facts)
    if _value(top, "d_s") is None and len(rungs) >= 3 and signals(rungs[:-1], policy)["d_s_settled"] \
            and _value(rungs[-2], "d_s") is not None:
        return make(STOP, "reading_lost",
                    f"d_s settled up to N={rungs[-2].n} and has no reading at N={top.n}: parked at the rung "
                    "that last read, with everything it measured kept",
                    facts=facts)
    judged = found.get("d_s_settled_by") or {}
    if found["d_s_step"] is None:
        d_s_part = "d_s has no reading at one of the last two rungs"
    elif judged.get("rule") == "measured":
        d_s_part = (f"the d_s step {judged['step']:.3f} is outside {policy.d_s_sigmas:g} measured errors "
                    f"({judged['noise']:.3f}) plus the finite-size tolerance ({judged['finite_size']:.3f})")
    elif found["d_s_sigma"] is None:
        d_s_part = "d_s has no standard error at one of the last two rungs"
    else:
        d_s_part = f"the d_s step is outside {policy.d_s_sigmas:g} standard errors"
    readings = (", ".join(found["other_probes"]) + " read at the top rung") if found["other_probes"] \
        else "no other probe reads"
    reason = f"{d_s_part}; {degree_part}; {readings}"
    if not policy.second_rung:
        streak = _unsettled_streak(rungs, policy)
        if policy.unsettled_rungs_to_park and streak >= int(policy.unsettled_rungs_to_park):
            facts["unsettled_streak"] = streak
            return make(STOP, "unsettled_twice",
                        f"unsettled at {streak} rungs in a row, through N={top.n}: parked with everything it "
                        f"measured kept ({reason})", facts=facts)
        return make(HOLD, "unsettled", reason, next_n=following, facts=facts)
    below = rungs[-2]
    if found["d_s_step"] is None and _value(top, "d_s") is None and _value(below, "d_s") is None:
        kind = G.refusal_kind(top.d_s_refusal) if top.d_s_refusal else "not known"
        at_cap = kind == "sampling" and any(seed.given_at_cap for seed in top.seeds)
        if at_cap:
            kind = "limits"
        facts["d_s_refusal"] = {"kind": kind, "bucket": top.d_s_refusal, "longer_chain": bool(top.longer_chain),
                                **({"given_at_cap": True} if at_cap else {})}
        if kind == "sampling" and not top.longer_chain:
            return make(RUN_NEXT, "longer_chain",
                        f"d_s has no reading at N={below.n} or N={top.n}, and at N={top.n} the probe refused "
                        f"it for the sampling ({top.d_s_refusal}): the rung once more with a longer chain, "
                        f"which may read it ({reason})", next_n=int(top.n), priority=2, facts=facts)
        after = ("; its longer chain did not read it either" if top.longer_chain else
                 "; a given chain ended at the mean-degree cap, which a longer chain reaches at the same move" if at_cap else "")
        return make(STOP, "no_reading",
                    f"d_s has no reading at N={below.n} or N={top.n}{after}: no next rung can form a step to "
                    f"judge; parked with everything it measured kept ({reason})", facts=facts)
    looks = _looks(rungs, policy)
    facts["unsettled_streak"] = looks
    k = int(policy.unsettled_rungs_to_park)
    if k and looks >= k:
        return make(STOP, "unsettled_twice",
                    f"d_s did not settle at {looks} rungs in a row, through N={top.n}: parked with everything "
                    f"it measured kept ({reason})", facts=facts)
    if following < policy.plateau_from_n:
        return make(RUN_NEXT, "second_rung",
                    f"{reason}; the next rung once, the look before a park (k = {k})",
                    next_n=following, priority=2, facts=facts)
    return make(STOP, "no_second_rung",
                f"{reason}; N={following} takes a plateau (464), so there is no second look: parked with "
                f"everything it measured kept", facts=facts)


def _looks(rungs: list, policy: Policy) -> int:
    looks, end = 0, len(rungs)
    while end >= 2 and int(rungs[end - 1].n) >= int(policy.base_sizes[-1]):
        found = signals(rungs[:end], policy)
        if found["d_s_settled"]:
            break
        looks += 1
        end -= 2 if found["d_s_across"] else 1
    return looks


def _unsettled_streak(rungs: list, policy: Policy) -> int:
    streak, end = 0, len(rungs)
    while end >= 2 and int(rungs[end - 1].n) >= int(policy.base_sizes[-1]):
        if d_s_pair(rungs[:end]) is None:
            break
        found = signals(rungs[:end], policy)
        if found["d_s_settled"]:
            break
        streak += 1
        end -= 2 if found["d_s_across"] else 1
    return streak
