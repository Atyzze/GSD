from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from graph_scale_dynamics.calibration import finite_size as F
from graph_scale_dynamics.decisions import depth as D
from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions import starts_rule as FS
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import apply, decide_pass, decision_inputs
from graph_scale_dynamics.decisions.engine import (
    PARKING_RULES, RUN_NEXT, STOP, Decision, Policy, Rung, Seed, decide)
from graph_scale_dynamics.decisions.every_chain import decide_every_chain
from graph_scale_dynamics.decisions.replay import replay_matches
from graph_scale_dynamics.research import gate_tree as T
from graph_scale_dynamics.research.outcome_ledger import build_outcome_ledger
from graph_scale_dynamics.research.stability_score import score_block

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
SEED = json.loads((ROOT / "calibration" / "seed_table.json").read_text(encoding="utf-8"))
SURVEY = Policy.from_spec(SPEC)
EVERY = Policy.from_spec({"engine": {"policy": dict(SPEC["engine"]["policy"], every_chain=True)}})
LAW = G.unsalted_law("law-", 0.10)
NAMES = ["empty", "random", "honeycomb", "cubic", "tesseract"]
CUBIC_HOLDS = {"honeycomb": ["melted", 0.1], "cubic": ["holds", 0.95], "tesseract": ["melted", 0.0]}


def rung(n, d_s=2.0, se=0.05, measured=None, *, md=3.0, small_world=0.0, d_v=1.0, seeds=()):
    return Rung(n=n, mean_degree=md, connected_fraction=1.0, probes=({} if d_s is None else {"d_s": (d_s, se)}),
                seeds_measured=3, seeds=tuple(seeds), measured_se=({} if measured is None else {"d_s": measured}),
                small_world_fraction=small_world, valid_fractions={"d_s": 1.0, "d_V": d_v})


def reading(classes: dict, *, fates=None, groups=None) -> dict:
    sizes = sorted(classes)
    read = [n for n in sizes if classes[n] != "not_read"]
    at = read[-1] if read else None
    return {"class": classes[at] if at else "not_read", "at_n": at, "top_n": sizes[-1],
            "by_n": {str(n): [classes[n], (groups or {}).get(n, [NAMES])] for n in sizes},
            "fates": fates or {}, "references": True}


def chosen(rule="d_s_settled", action=RUN_NEXT, at_n=4096, next_n=16384, priority=1, law=LAW, facts=None):
    return Decision(law=law, action=action, rule=rule, reason=f"d_s: {rule}", at_n=at_n, next_n=next_n,
                    priority=priority, facts=facts if facts is not None else {"mean_degree": 3.0})


BASE = [rung(64), rung(256), rung(1024)]


def _flow(family: str) -> list[tuple[int, float, float]]:
    values: dict = {}
    for cell in SEED["cells"].values():
        channel = cell["channels"].get("d_s") or {}
        if cell["family"] == family and channel.get("valid"):
            values.setdefault(int(cell["n"]), []).append(float(channel["value"]))
    out = []
    for n, d in F.in_the_flow(F._means(SEED)[family]):
        v = values[n]
        spread = math.sqrt(sum((x - d) ** 2 for x in v) / max(1, len(v) - 1))
        out.append((n, d, spread / math.sqrt(len(v))))
    return out


def test_square_and_cubic_lattice_chains_settle_by_the_measured_rule_and_a_small_world_s_climb_does_not():
    for family in ("periodic_square_lattice", "periodic_cubic_lattice"):
        chain = [rung(n, d, se=err, measured=err) for n, d, err in _flow(family)]
        for end in range(2, len(chain) + 1):
            found = E.signals(chain[:end], SURVEY)
            assert found["d_s_settled"] and found["d_s_settled_by"]["rule"] == "measured", (family, end, found)
            assert found["d_s_settled_by"]["finite_size"] > 0
    climb = [rung(4096, 6.0, se=0.05, measured=0.05), rung(16384, 7.0, se=0.05, measured=0.05)]
    found = E.signals(climb, SURVEY)
    assert not found["d_s_settled"] and found["d_s_settled_by"]["rule"] == "measured"


def test_a_reading_without_the_measured_error_keeps_the_se_rule_exactly_and_says_so():
    for step, settled in ((0.05, True), (0.3, False)):
        plain = [rung(4096, 2.0, se=0.06), rung(16384, 2.0 + step, se=0.06)]
        assert E.signals(plain, SURVEY)["d_s_settled"] is settled, "within twice the two se, as the rule always was"
        assert E.signals(plain, SURVEY)["d_s_settled_by"]["rule"] == "se"
    half = [rung(4096, 2.0, se=0.06, measured=0.01), rung(16384, 2.5, se=0.06)]
    assert E.signals(half, SURVEY)["d_s_settled_by"]["rule"] == "se", "both readings must carry it"


def test_the_decision_records_what_judged_its_step_and_replays():
    rungs = BASE + [rung(4096, 2.10, measured=0.02), rung(16384, 2.03, measured=0.02)]
    decision = decide(LAW, rungs, SURVEY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "d_s_settled", 65536)
    assert decision.facts["d_s_settled_by"]["rule"] == "measured"
    unsettled = decide(LAW, BASE + [rung(4096, 2.0, measured=0.01), rung(16384, 3.0, measured=0.01)], SURVEY)
    assert "measured errors" in unsettled.reason and "finite-size tolerance" in unsettled.reason
    inputs = decision_inputs(LAW, rungs, SURVEY)
    assert inputs["rules_revision"] == E.rules_revision(SURVEY) == E.RULES_REVISION == 782
    assert decision_inputs(LAW, rungs, Policy())["rules_revision"] == 782, "the clock's revision (782)"
    row = json.loads(json.dumps(decision.as_dict() | {"inputs": inputs}, default=str))
    assert replay_matches(row)["matches"], replay_matches(row)


SQUARE_FLOW_5_0 = ((144, 2.251812, 0.031974), (256, 2.16342, 0.011788), (576, 2.10912, 0.010397),
                   (1024, 2.067697, 0.012786), (2304, 2.032758, 0.008472), (4096, 2.012512, 0.006378))


def test_the_stability_score_judges_d_s_steps_by_the_same_rule():
    sizes, values, errors = zip(*SQUARE_FLOW_5_0, strict=True)
    measured = score_block(list(values), [None] * 6, floor=0.01, sizes=list(sizes), ses=[0.01] * 6,
                           measured_ses=list(errors))
    assert measured["tolerance_rule"].startswith("measured") and measured["bucket"] == "CONVERGED"
    plain = score_block(list(values), [None] * 6, floor=0.01, sizes=list(sizes), ses=[0.01] * 6)
    assert "tolerance_rule" not in plain and plain["bucket"] != "CONVERGED", "a 0.01 floor calls its flow drift"
    climb = score_block([4.0, 5.0, 6.0, 7.0], [None] * 4, floor=0.3, sizes=[1024, 4096, 16384, 65536],
                        ses=[0.4] * 4, measured_ses=[0.05] * 4)
    assert climb["bucket"] != "CONVERGED"


def test_the_survey_climbs_to_a_million_and_a_salt_never_past_65536():
    assert SURVEY.ladder()[-1] == 1048576 and 4194304 not in SURVEY.ladder()
    assert SURVEY.lane_rungs() == (1048576,) and SURVEY.deep_lane_width(1048576) == 4
    assert E.rules_revision(SURVEY) == E.RULES_REVISION == 782
    assert SURVEY.salt_share("starts_alike", 4096) == 0.10, "below 16,384 the salt is as it was"
    assert SURVEY.salt_share("starts_alike", 16384) == SURVEY.deep_salt_at_most == 0.005
    assert SURVEY.salt_share("no_finite_dimension", 65536) == 0.0 == SURVEY.salt_share("empty", 262144)


PLATEAU = BASE + [rung(4096, 2.10, measured=0.02), rung(16384, 2.04, measured=0.02)]


def test_past_65536_only_a_promising_law_buys_its_rung():
    good = decide(LAW, PLATEAU + [rung(65536, 2.01, measured=0.02)], SURVEY)
    assert (good.action, good.rule, good.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert good.facts["promising"]["passes"] and set(good.facts["promising"]["checks"]) == {
        "shaped", "not_small_world", "d_s_settled", "d_V_valid"}
    for top, failed in ((rung(65536, 2.01, measured=0.02, small_world=0.67), "not_small_world"),
                        (rung(65536, 2.01, measured=0.02, d_v=1 / 3), "d_V_valid"),
                        (rung(65536, 2.01, measured=0.02, small_world=None), "not_small_world")):
        refused = decide(LAW, PLATEAU + [top], SURVEY)
        assert (refused.action, refused.rule, refused.next_n) == (STOP, D.NOT_PROMISING, None)
        assert refused.rule in PARKING_RULES and not refused.facts["promising"]["checks"][failed]["passes"]
        assert refused.facts["refused"] == {"action": RUN_NEXT, "rule": "d_s_settled", "next_n": 262144,
                                            "priority": 1}
    below = decide(LAW, BASE + [rung(4096, 2.10, measured=0.02, small_world=1.0)], SURVEY)
    assert below.rule == "d_s_settled" and "promising" not in below.facts, "below 262,144 the bar is silent"


def test_a_law_decided_by_its_starts_must_be_shaped_at_its_top_two_rungs():
    rungs = PLATEAU + [rung(65536, 2.01, measured=0.02)]
    both = reading({4096: "selects", 16384: "selects", 65536: "selects"}, fates=CUBIC_HOLDS)
    chains = {"empty": rungs, "cubic": rungs}
    bought = decide_every_chain(LAW, chains, EVERY, starts_reading=both)
    assert (bought.action, bought.rule, bought.next_n) == (RUN_NEXT, FS.SHAPE, 262144) and bought.priority == 1
    assert bought.facts["promising"]["checks"]["shaped"]["classes"] == {"65536": "selects", "16384": "selects"}
    once = reading({4096: "selects", 16384: "remembers", 65536: "selects"}, fates=CUBIC_HOLDS)
    refused = decide_every_chain(LAW, chains, EVERY, starts_reading=once)
    assert (refused.action, refused.rule) == (STOP, D.NOT_PROMISING)
    assert "not shaped at both of its top two rungs" in refused.reason


APART_FROM_THE_CUBIC = {n: [["cubic"], ["empty", "random", "honeycomb", "tesseract"]] for n in (16384, 65536)}


def test_the_bar_is_read_on_the_chain_that_carries_the_shape():
    shaped = reading({4096: "selects", 16384: "selects", 65536: "selects"}, fates=CUBIC_HOLDS,
                     groups=APART_FROM_THE_CUBIC)
    small_world = PLATEAU[:-2] + [rung(4096, 5.0, measured=0.05, small_world=1.0),
                                  rung(16384, 6.0, measured=0.05, small_world=1.0),
                                  rung(65536, 7.0, measured=0.05, small_world=1.0)]
    cubic = BASE + [rung(4096, 2.80, measured=0.02), rung(16384, 2.90, measured=0.02),
                    rung(65536, 2.93, measured=0.02)]
    passed = decide_every_chain(LAW, {"empty": small_world, "cubic": cubic}, EVERY, starts_reading=shaped)
    assert (passed.action, passed.rule, passed.next_n) == (RUN_NEXT, FS.SHAPE, 262144)
    reading_ = passed.facts["promising"]
    assert reading_["passed_by"] == ["cubic"] and set(reading_["chains"]) == {"cubic"}, "the chain from empty carries nothing"
    assert reading_["chains"]["cubic"]["checks"]["d_s_settled"]["judged_by"]["rule"] == "measured"
    melted = BASE + [rung(n, d, measured=0.02, small_world=1.0)
                     for n, d in ((4096, 2.80), (16384, 2.90), (65536, 2.93))]
    refused = decide_every_chain(LAW, {"empty": small_world, "cubic": melted}, EVERY, starts_reading=shaped)
    assert (refused.action, refused.rule) == (STOP, D.NOT_PROMISING)
    assert not refused.facts["promising"]["chains"]["cubic"]["checks"]["not_small_world"]["passes"]
    assert "no chain that carries its shape is promising" in refused.reason
    together = reading({4096: "selects", 16384: "selects", 65536: "selects"}, fates=CUBIC_HOLDS)
    from_empty_too = decide_every_chain(LAW, {"empty": cubic, "cubic": melted}, EVERY, starts_reading=together)
    assert from_empty_too.facts["promising"]["passed_by"] == ["empty"], "the chain from empty, where it carries the shape"


def test_a_given_chain_carries_its_measured_error_and_small_world_flag_to_its_rung():
    from graph_scale_dynamics.decisions.every_chain import chain_metrics
    from graph_scale_dynamics.decisions.rungs import rung_from_entry
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    given = {"d_s": {"valid": True, "value": 2.9, "se": 0.3, "measured_se": 0.02}, "small_world": False}
    metrics = [chain_metrics({"chain_probes": {"given": dict(given, d_s=dict(given["d_s"], value=v))},
                              "census": {"given": {"n": 4096, "edges": 12288,
                                                     "largest_component": {"size": 4096}}}}, 0, "cubic")
               for v in (2.88, 2.90, 2.92)]
    summary = rung_summary(metrics)
    assert summary["small_world_fraction"] == 0.0 and 0.0 < summary["d_s_measured_se"] < 0.05
    entry = {"mean_degree": 6.0, "d_s": 2.9, "d_s_bucket": None, "small_world_fraction": 0.0,
             "probes": {"d_s": {"se": 0.3, "measured_se": summary["d_s_measured_se"]}}, "d_V_valid_fraction": 1.0}
    built = rung_from_entry(4096, entry)
    assert built.measured_se["d_s"] == summary["d_s_measured_se"] and built.small_world_fraction == 0.0


def test_the_seeds_a_merit_rung_is_short_of_keep_its_budget():
    shaped = reading({1024: "selects", 4096: "selects", 16384: "selects"}, fates=CUBIC_HOLDS)
    short = PLATEAU[:-1] + [Rung(n=16384, mean_degree=3.0, connected_fraction=1.0, probes={"d_s": (2.04, 0.05)},
                                 seeds_measured=2)]
    completing = decide_every_chain(LAW, {"empty": short}, EVERY, starts_reading=shaped)
    assert (completing.rule, completing.next_n) == ("complete_rung", 16384)
    assert completing.facts["budget_scale"] == 2.0 and D.budget_scale(completing, EVERY) == 2.0
    apart = reading({1024: "remembers", 4096: "remembers", 16384: "remembers"})
    looked = decide_every_chain(LAW, {"empty": short}, EVERY, starts_reading=apart)
    assert "budget_scale" not in looked.facts and D.budget_scale(looked, EVERY) == 1.0


def test_a_salted_law_never_buys_past_65536():
    salted = chosen("salted", at_n=65536, next_n=262144, priority=2, facts={"salted": ["starts_alike"]})
    refused = D.bar(LAW, salted, PLATEAU + [rung(65536, 2.01, measured=0.02)], SURVEY)
    assert (refused.action, refused.rule) == (STOP, D.NOT_PROMISING) and refused.facts["promising"]["salted"]


def test_the_structure_gate_at_65536_acts():
    assert SURVEY.gate_at_n == 65536 and 262144 in SURVEY.ladder(), "a rung above 65,536 exists for it to decide"
    assert SURVEY.salt_share("no_finite_dimension", 65536) == 0.0, "and no salt carries a refusal past it"


class Store:
    def __init__(self):
        self.calls = []

    def enqueue_seeds(self, campaign_id, law, n, **kwargs):
        self.calls.append((n, kwargs))
        return 3

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        return 1


def test_a_shape_buy_runs_with_twice_its_budget():
    store = Store()
    apply(store, "1", chosen(FS.SHAPE, at_n=4096, next_n=16384), EVERY)
    apply(store, "1", chosen(FS.APART, at_n=4096, next_n=16384, priority=2), EVERY)
    (_, shape), (_, apart) = store.calls
    assert shape["budget_scale"] == 2.0 and shape["work_budget"] == 2 * EVERY.work_budget(16384)
    assert "budget_scale" not in apart


def test_the_jobs_carry_the_larger_budget_to_the_child_and_no_timeout():
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scheduling.job_creation import enqueue_simulation_rung
    from graph_scale_dynamics.scheduling.limits import work_budget
    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())

    class Repo:
        jobs = []

        def insert_job(self, **fields):
            self.jobs.append(fields)
            return True

    class Log:
        def write(self, *args, **kwargs):
            pass

    repo = Repo()
    enqueue_simulation_rung(repo, Log(), {"campaign_id": "c", "spec": SPEC},
                            {"candidate_id": fingerprint(law), "spec": law}, 16384, [0], "decider", budget_scale=2.0)
    job = repo.jobs[0]["spec"]
    assert job["execution"]["one_shot"]["work_budget"] == 2 * work_budget(SPEC, 16384)
    assert "timeout_seconds" not in job, "no clock watches the child: a lost process is the lease's to catch"


def _ended_at_its_budget(n=16384):
    budget = EVERY.work_budget(n)
    seeds = (Seed("completed", work_units=budget // 10, work_budget=budget),
             Seed("budget", work_units=budget, work_budget=budget),
             Seed("completed", work_units=budget // 5, work_budget=budget))
    return PLATEAU[:-1] + [rung(n, 2.04, measured=0.02, seeds=seeds)]


def test_a_shape_buy_a_seed_of_which_ended_at_its_budget_is_read_and_decided_as_any_other_and_marked():
    shaped = reading({1024: "selects", 4096: "selects", 16384: "selects"}, fates=CUBIC_HOLDS)
    rungs = _ended_at_its_budget()
    now = decide_every_chain(LAW, {"empty": rungs, "cubic": rungs}, EVERY, starts_reading=shaped)
    assert now.action != STOP and now.facts["budget_ended"]["seeds"] == [1]


def test_a_shaped_class_is_not_overridden_by_the_empty_chain_s_stop():
    empty = [rung(n, None, md=0.0) for n in (64, 256, 1024, 4096)]
    lattice = BASE + [rung(4096, None)]
    shaped = reading({1024: "holds", 4096: "holds"}, fates=CUBIC_HOLDS)
    decision = decide_every_chain(LAW, {"empty": empty, "cubic": lattice}, EVERY, starts_reading=shaped)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, FS.SHAPE, 16384)
    assert decision.facts["shape_over_verdict"]["empty"]["rule"] == "empty"
    assert decision.facts["earned_by"] == "cubic"


def test_a_longer_chain_runs_only_where_the_starts_would_not_park():
    sampling = chosen("longer_chain", at_n=4096, next_n=4096, priority=2,
                      facts={"d_s_refusal": {"kind": "sampling", "bucket": "REFUSED_NEVER_EQUILIBRATED"}})
    alike = reading({1024: "forgets", 4096: "forgets"})
    parked = FS.decide(LAW, sampling, alike, EVERY, BASE)
    assert (parked.action, parked.rule) == (STOP, FS.ALIKE) and parked.facts["longer_chain_skipped"]
    shaped = reading({1024: "selects", 4096: "selects"}, fates=CUBIC_HOLDS)
    assert FS.decide(LAW, sampling, shaped, EVERY, BASE).rule == "longer_chain", "the rung's own reading first"


def test_the_apart_look_reads_the_class_history():
    forgot = FS.decide(LAW, chosen(), reading({1024: "forgets", 4096: "remembers"}), EVERY, BASE)
    assert (forgot.action, forgot.rule) == (STOP, FS.APART_BY_HISTORY) and forgot.rule in PARKING_RULES
    assert FS.APART_BY_HISTORY in G.SALTED_GATES and FS.APART_BY_HISTORY in FS.PARKS
    two = FS.decide(LAW, chosen(), reading({1024: "remembers", 4096: "remembers"},
                                           groups={4096: [["empty", "random"], ["honeycomb", "cubic", "tesseract"]]}),
                    EVERY, BASE)
    assert two.rule == FS.APART_BY_HISTORY and "two groups" in two.reason
    selected = FS.decide(LAW, chosen(), reading({1024: "selects", 4096: "remembers"}), EVERY, BASE)
    assert (selected.rule, selected.priority) == (FS.APART, 1)
    plain = FS.decide(LAW, chosen(), reading({1024: "remembers", 4096: "remembers"}), EVERY, BASE)
    assert (plain.rule, plain.priority) == (FS.APART, 2)


def _row(law, at_n, next_n, rule, *, action=RUN_NEXT, classes=None, settled=None, salted_from=None, i=0):
    facts = {}
    if classes is not None:
        facts["starts_reading"] = {"decided": True, "classes": {str(n): c for n, c in classes.items()}}
    if settled is not None:
        facts["d_s_settled"] = settled
    if salted_from:
        facts["salted_from"] = {"rule": salted_from}
    return {"decision_id": f"{i:04d}", "law": law, "at_n": at_n, "next_n": next_n, "rule": rule, "action": action,
            "facts": facts}


def test_the_outcome_ledger_says_whether_each_buy_s_reason_held_and_feeds_the_parks_salts():
    decisions = {
        "a": [_row("a", 4096, 16384, FS.SHAPE, classes={4096: "selects"}, i=1),
              _row("a", 16384, 65536, FS.SHAPE, classes={16384: "selects"}, i=2)],
        "b": [_row("b", 4096, 16384, FS.SHAPE, classes={4096: "selects"}, i=3),
              _row("b", 16384, None, FS.ALIKE, action=STOP, classes={16384: "forgets"}, i=4)],
        "c": [_row("c", 4096, 16384, "salted", classes={4096: "forgets"}, salted_from=FS.ALIKE, i=5),
              _row("c", 16384, 65536, FS.SHAPE, classes={16384: "holds"}, i=6)],
        "d": [_row("d", 4096, 16384, "d_s_settled", settled=True, i=7),
              _row("d", 16384, None, "no_reading", action=STOP, i=8)],
    }
    ledger = build_outcome_ledger(decisions)
    rows = {(r["rule"], r["from_n"]): r for r in ledger["rules"]}
    assert (rows[(FS.SHAPE, 4096)]["bought"], rows[(FS.SHAPE, 4096)]["held"], rows[(FS.SHAPE, 4096)]["hit_rate"]) == (
        2, 1, 0.5)
    assert rows[(FS.SHAPE, 16384)]["open"] == 2 and rows[("d_s_settled", 4096)]["not_read"] == 1
    assert rows[("salted", 4096)]["held"] == 1, "the salted law found a shape"
    park = ledger["salt_by_gate"][FS.ALIKE][T.CHEAP]
    assert park[T.MISSED] == 1 and park["label"] == "testing", (
        "the park's salts are judged by the shapes they found, not the structure rule that seldom reads them")


def test_report_28_carries_the_outcome_ledger_and_the_parks_salts_ride_in_its_gate_tree():
    from graph_scale_dynamics.research.decision_engine_report import build_decision_engine_report
    decisions = {"c": [_row("c", 4096, 16384, "salted", classes={4096: "forgets"}, salted_from=FS.ALIKE, i=5),
                       _row("c", 16384, None, FS.ALIKE, action=STOP, classes={16384: "forgets"}, i=6)]}
    report = build_decision_engine_report({"campaign": {"spec": SPEC}, "engine_decisions": decisions}, EVERY)
    assert report["outcome_ledger"]["rules"][0]["rule"] == "salted"
    assert report["gate_tree"]["salt_outcomes"][FS.ALIKE][T.CHEAP][T.CLEAN] == 1


def test_the_deep_salt_is_at_most_half_a_percent():
    assert EVERY.salt_share(FS.APART_TWICE, 16384) == 0.005
    shares = Policy(depth_rules=629, salt_shares=((FS.APART_TWICE, 0.5, 0.1),))
    assert shares.salt_share(FS.APART_TWICE, 16384) == 0.005 and shares.salt_share(FS.APART_TWICE, 4096) == 0.5
    parked, merit = 3291, 157
    assert parked * 0.005 / (parked * 0.005 + merit) < 0.15, "3,291 parked laws at 65,536 at this share: about 9% salt"


def _unsettled(n_top):
    return BASE + [rung(n, 3.0 + i, se=0.05) for i, n in enumerate(n for n in (4096, 16384) if n <= n_top)]


def test_dec_1_a_ladder_that_ends_below_the_plateau_rung_has_no_lane_there():
    short = dict(deep_sizes=(16384, 65536), work_budgets=tuple(row for row in Policy().work_budgets if row[0] <= 65536))
    after = Policy(**short)
    assert 65536 not in after.lane_rungs()
    law = next(f"law-{i}" for i in range(100000) if G.salted(f"law-{i}", "unsettled_twice", 0.005))
    bought = decide(law, _unsettled(16384), after, deep_lane_in_flight={65536: 9})
    assert (bought.action, bought.rule, bought.next_n) == (RUN_NEXT, "salted", 65536)


def test_dec_3_the_apart_look_is_once_when_the_starts_go_unread():
    unread = reading({1024: "remembers", 4096: "remembers", 16384: "not_read"})
    at_16384 = chosen(at_n=16384, next_n=65536)
    parked = FS.decide(LAW, at_16384, unread, EVERY, BASE)
    assert (parked.action, parked.rule) == (STOP, FS.APART_TWICE)
    between = reading({4096: "selects", 16384: "not_read", 65536: "remembers"}, fates=CUBIC_HOLDS)
    look = FS.decide(LAW, chosen(at_n=65536, next_n=262144), between, EVERY, BASE)
    assert look.rule == FS.APART, "a size a shape bought and left unread is not an apart look"


ONCE = Policy.from_spec({"engine": {"policy": dict(SPEC["engine"]["policy"], every_chain=True, depth_rules=631)}})


def test_dec_3_for_shapes_a_shape_read_below_unread_sizes_buys_only_its_one_size():
    shaped = {1024: "selects", 4096: "selects"}
    unread = reading({**shaped, 16384: "not_read"}, fates=CUBIC_HOLDS)
    at_16384 = chosen(at_n=16384, next_n=65536)
    assert E.rules_revision(ONCE) == E.RULES_REVISION == 782
    parked = FS.decide(LAW, at_16384, unread, ONCE, BASE)
    assert (parked.action, parked.rule, parked.next_n) == (STOP, FS.SHAPE_UNREAD, None)
    assert parked.rule in PARKING_RULES and parked.rule in G.SALTED_GATES and parked.rule in FS.PARKS
    assert parked.facts["shape_unread"] == {"read_at": 4096, "unread": [16384]} and "N=16,384" in parked.reason
    first = FS.decide(LAW, chosen(), reading(shaped, fates=CUBIC_HOLDS), ONCE, BASE)
    assert (first.rule, first.next_n, first.priority) == (FS.SHAPE, 16384, 1)
    low = FS.decide(LAW, chosen(), reading({1024: "selects", 4096: "not_read"}, fates=CUBIC_HOLDS), ONCE, BASE)
    assert (low.rule, low.next_n) == (FS.SHAPE, 16384)
    lower = FS.decide(LAW, at_16384, reading({1024: "selects", 4096: "not_read", 16384: "not_read"},
                                             fates=CUBIC_HOLDS), ONCE, BASE)
    assert lower.rule == FS.SHAPE_UNREAD and lower.facts["shape_unread"]["unread"] == [16384]
    read_again = reading({**shaped, 16384: "not_read", 65536: "selects"}, fates=CUBIC_HOLDS)
    assert FS.decide(LAW, chosen(at_n=65536, next_n=262144), read_again, ONCE, BASE).rule == FS.SHAPE
    rungs = BASE + [rung(4096, 2.10), rung(16384, 2.11)]
    whole = decide_every_chain(LAW, {"empty": rungs}, ONCE, starts_reading=unread)
    assert (whole.action, whole.rule) == (STOP, FS.SHAPE_UNREAD)


def test_a_shape_s_unread_park_lets_its_salt_one_size_on():
    deep = Policy.from_spec({"engine": {"policy": dict(SPEC["engine"]["policy"], every_chain=True, depth_rules=631,
                                                         promising_from_n=1048576)}})
    share = deep.salt_share(FS.SHAPE_UNREAD, 16384)
    assert share == 0.005, "a deep park's salt is at most half a percent"
    law = next(f"law-{i}" for i in range(200000) if G.salted(f"law-{i}", FS.SHAPE_UNREAD, share))
    shaped = {1024: "selects", 4096: "selects", 16384: "not_read"}
    salted = FS.decide(law, chosen(at_n=16384, next_n=65536, law=law), reading(shaped, fates=CUBIC_HOLDS), deep, BASE)
    assert (salted.action, salted.rule, salted.next_n) == (RUN_NEXT, "salted", 65536)
    assert salted.facts["salted_from"]["rule"] == FS.SHAPE_UNREAD
    spent = FS.decide(law, chosen(at_n=65536, next_n=262144, law=law),
                      reading({**shaped, 65536: "not_read"}, fates=CUBIC_HOLDS), deep, BASE)
    assert (spent.action, spent.rule) == (STOP, FS.SHAPE_UNREAD)
    assert spent.facts["salt_spent"] == {"gate": FS.SHAPE_UNREAD, "salted_at": 16384, "held_at": 65536}


def test_dec_4_a_seed_that_completed_did_not_reach_its_budget():
    budget = SURVEY.work_budget(256)
    seeds = tuple(Seed("completed", work_units=units, work_budget=budget) for units in (budget // 5, budget // 7, budget))
    rungs = [rung(64), rung(256, seeds=seeds)]
    after = decide(LAW, rungs, SURVEY)
    assert after.rule == "base_block" and not any(u["reached"] for u in after.facts["budget_use"])
    reached = decide(LAW, [rung(64), rung(256, seeds=(Seed("budget", work_units=budget, work_budget=budget),) * 3)],
                     SURVEY)
    assert reached.rule == "base_block" and reached.facts["budget_ended"] == {"seeds": [0, 1, 2], "of": 3, "at_n": 256}
    unknown = decide(LAW, [rung(64), rung(256, seeds=(Seed(None, work_units=2 * budget),) * 3)], SURVEY)
    assert "budget_ended" not in unknown.facts, "only the run's own end at its budget marks it, never what it spent"


class DecStore:
    def __init__(self, evidence, *, undecidable=None):
        self.evidence, self.undecidable_why = evidence, undecidable
        self.decisions, self.pending, self.failures = [], [], []

    def laws_awaiting_decision(self, campaign_id):
        return [LAW]

    def law_evidence(self, campaign_id, law):
        if isinstance(self.evidence, Exception):
            raise self.evidence
        return self.evidence

    def record_pending(self, campaign_id, law, reasons):
        self.pending.append(tuple(reasons))

    def record_failure(self, campaign_id, law, error):
        self.failures.append(error)

    def undecidable(self, campaign_id, law):
        return self.undecidable_why

    def record_phenotype(self, *args):
        pass

    def seed_rows(self, campaign_id, law):
        return {}

    def set_law_state(self, campaign_id, law, state, *, rule, next_n):
        return 1

    def record_decision(self, campaign_id, row):
        self.decisions.append(row)

    def queue_depth(self, campaign_id):
        return 1

    def held_laws(self, campaign_id, limit=None):
        return []


def test_dec_6_a_law_that_can_never_be_decided_is_stopped_with_its_reason_and_a_pending_one_is_said():
    failed = DecStore({"entries": {}, "phenotype": None, "evidence_failed": "its evidence rebuild failed for good"})
    tally = decide_pass(failed, "1", SURVEY)
    (row,) = failed.decisions
    assert (row["action"], row["rule"]) == (STOP, "failed") and "rebuild failed for good" in row["reason"]
    assert row["inputs"]["evidence_failed"] and replay_matches(json.loads(json.dumps(row, default=str)))["matches"]
    pending = DecStore({"pending": True, "pending_reasons": ["evidence rebuild not finished"]})
    tally = decide_pass(pending, "1", SURVEY)
    assert pending.pending == [("evidence rebuild not finished",)] and pending.decisions == []
    assert tally[("pending", "evidence rebuild not finished")] == 1
    raising = DecStore(KeyError("unmapped refusal"), undecidable="reading it failed the same way on 5 passes")
    tally = decide_pass(raising, "1", SURVEY)
    assert raising.failures and raising.decisions[0]["rule"] == "failed" and tally[(STOP, "undecidable")] == 1
    once = DecStore(KeyError("unmapped refusal"))
    decide_pass(once, "1", SURVEY)
    assert once.decisions == [], "a failure the store does not yet call lasting decides nothing"


def test_dec_6_a_transient_database_error_never_counts_toward_the_stop():
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    from graph_scale_dynamics.decisions.decider import transient
    timeout = DatabaseOperationalError("canceling statement due to statement timeout", transient=True,
                                       sqlstate="57014")
    counted = []
    store = DecStore(timeout, undecidable="reading it failed the same way on 5 passes")
    store.count_failure = lambda campaign_id, law, error: counted.append(error)
    decide_pass(store, "1", SURVEY)
    assert store.failures and store.decisions == [] and counted == [], "said, never counted, never stopped"
    try:
        try:
            raise timeout
        except DatabaseOperationalError as inner:
            raise RuntimeError("reading the law's evidence") from inner
    except RuntimeError as wrapped:
        assert transient(wrapped), "a transient cause makes the failure transient"
    assert not transient(KeyError("unmapped")) and not transient(DatabaseOperationalError("syntax", sqlstate="42601"))


def test_dec_6_the_store_counts_a_lasting_failure_and_forgets_it_once_the_law_is_decided():
    from graph_scale_dynamics.db import decision_store as S

    class Repo:
        def emit(self, *args):
            pass

    class Log:
        def write(self, *args, **kwargs):
            pass

    store = S.DecisionStore.__new__(S.DecisionStore)
    store.repo, store.log = Repo(), Log()
    for _ in range(S.UNDECIDABLE_PASSES):
        store.count_failure("c", "x", "KeyError: 'unmapped'")
    assert store.undecidable("c", "x") is None, "not yet an hour"
    S._FAILING[("c", "x")]["since"] -= S.UNDECIDABLE_SECONDS + 1
    assert "5 passes" in store.undecidable("c", "x")
    store.count_failure("c", "x", "another error")
    assert store.undecidable("c", "x") is None, "another error starts again"
    S._FAILING.pop(("c", "x"), None)


def test_the_law_standing_is_the_law_score_this_pass_kept_and_the_family():
    from graph_scale_dynamics.db import decision_store as S
    store = S.DecisionStore.__new__(S.DecisionStore)
    store.spec, store.policy, store._calibration = SPEC, Policy.from_spec(SPEC), {}
    store.scored = {"law-a": {"score": 57.1, "by": "empty"}}
    store.control_family = lambda phenotype: "random_regular_3"
    assert store.law_standing("law-a", {"per_n": {}}) == {"control_family": "random_regular_3", "law_score": 57.1}
    assert store.law_standing("law-b", None) == {"control_family": None, "law_score": None}


def test_every_new_rule_is_a_named_stream_and_an_older_campaign_keeps_its_fingerprint():
    streams = Counter((s.action, s.rule) for s in G.STREAMS)
    for key in ((STOP, D.NOT_PROMISING), (STOP, FS.APART_BY_HISTORY)):
        assert streams[key] == 1
    assert E.policy_fingerprint(Policy()) == E.policy_fingerprint(Policy(depth_rules=0, deep_salt_at_most=0.005))
    assert E.policy_fingerprint(SURVEY) != E.policy_fingerprint(Policy.from_spec(
        {"engine": {"policy": dict(SPEC["engine"]["policy"], depth_rules=0)}}))
