from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import law_rows as L  # noqa: E402
import pattern_scan as P  # noqa: E402
import sample_reading as S  # noqa: E402

OPS = ("degree_anchor", "degree_neighbor_gradient", "square_count", "edge_count", "triangle_count")


def _law(rng: random.Random, campaign: int, k: int, *, zero_share: float, plant_everywhere: bool,
         plant_first_half: bool) -> tuple[dict, dict, dict]:
    law = f"{campaign:02d}{k:04d}".ljust(64, "0")
    ops = rng.sample(OPS, rng.randint(1, 3))
    terms = [[op, 8 if op == "degree_anchor" else None, rng.choice((-1.0, 1.0)), rng.choice(("one", "log_N")), None]
             for op in ops]
    zero = rng.random() < zero_share
    gradient = any(t[0] == "degree_neighbor_gradient" and t[2] > 0 for t in terms)
    triangles = any(t[0] == "triangle_count" for t in terms)
    holds = (plant_everywhere and gradient and rng.random() < 0.6) or (
        plant_first_half and campaign <= 2 and triangles and rng.random() < 0.6) or rng.random() < 0.02
    fate = rng.choice((["empty", 256], ["too_dense", 256], ["starts_alike", 4096], ["starts_alike", 4096]))
    read = fate[1] == 4096
    row = {"candidate_id": law, "admitted_utc": f"2026-10-0{1 + k % 9}T{k % 24:02d}:{k % 60:02d}:00Z",
           "fate": fate, "kind": "sees cycles" if "square_count" in ops or "triangle_count" in ops else
           ("degree correlations" if "degree_neighbor_gradient" in ops else "degree sequence only"),
           "mean_degree": {"4096": 3.0}, "spec": {"zero_temperature": zero, "beta": 2.0, "terms": terms,
                                                  "local_move": "toggle", "locality": 0.5, "swap_share": 0.5,
                                                  "sweeps": 30}}
    chain = {"top_n": 4096, "score": {"score": 9 if holds else 0, "by": "lattice" if holds else None},
             "starts_reading": {"class": ("selects" if holds else rng.choice(("forgets", "remembers"))) if read else None,
                             "by_n": {"1024": ["forgets"]} if read else {},
                             "fates": {"cubic": ["holds" if holds else "melted", 0.9],
                                       "honeycomb": ["melted", 0.0], "tesseract": ["melted", 0.0]}}} if read else {}
    return row, chain, {"candidate_id": law, "action": "stop", "rule": fate[0]}


def bundle(root: Path, *, laws: int = 300, zero_share=(0.5, 0.5, 0.5, 0.5), plant_everywhere: bool = True,
           plant_first_half: bool = False, seed: int = 7) -> Path:
    rng = random.Random(seed)
    records = []
    for campaign in (1, 2, 3, 4):
        folder = root / f"campaign_{campaign}"
        folder.mkdir(parents=True)
        made = [_law(rng, campaign, k, zero_share=zero_share[campaign - 1], plant_everywhere=plant_everywhere,
                     plant_first_half=plant_first_half) for k in range(laws)]
        body = {"law_ledger": {"rows": [m[0] for m in made]}, "laws": [m[2] for m in made],
                "every_chain": {"laws": {m[0]["candidate_id"]: m[1] for m in made if m[1]}}}
        (folder / "28-decision-engine.json").write_text(json.dumps({"body": body}))
        records.append({"campaign_id": str(campaign), "bundle": folder.name, "law_budget": 1000,
                        "laws_held": laws})
    control = root / "campaign_5"
    control.mkdir()
    (control / "28-decision-engine.json").write_text(json.dumps({"body": {"law_ledger": {"rows": []}}}))
    records.append({"campaign_id": "5", "bundle": control.name})
    (root / "study.json").write_text(json.dumps({"campaigns": records}))
    return root


def test_the_rows_are_the_study_s_own_laws_and_what_their_starts_read(tmp_path):
    rows = L.rows(bundle(tmp_path))
    assert len(rows) == 1200 and {r["campaign"] for r in rows} == {"1", "2", "3", "4"}, "the control is left out"
    assert L.budget(tmp_path) == 4000
    read = [r for r in rows if L.read_by_the_starts(r)]
    assert read and all(r["fates"].keys() == {"cubic", "honeycomb", "tesseract"} for r in read)
    assert any(L.held(r, "cubic") for r in read) and not any(L.held(r, "tesseract") for r in read)


def test_campaigns_drawn_alike_read_as_one_sample_and_one_drawn_otherwise_does_not(tmp_path):
    alike = S.campaigns_against_chance(L.rows(bundle(tmp_path / "alike")))
    assert alike["one_sample"], alike["lowest_p"]
    assert {r["reading"] for r in alike["readings"]} >= {"the outcome at 256", "the drawn temperature"}
    apart = S.campaigns_against_chance(L.rows(bundle(tmp_path / "apart", zero_share=(0.5, 0.5, 0.5, 0.95))))
    worst = min(apart["readings"], key=lambda r: r["p"])
    assert not apart["one_sample"] and worst["reading"] == "the drawn temperature", worst


def test_what_more_laws_buy_scales_each_reading_to_the_budget(tmp_path):
    rows = L.rows(bundle(tmp_path))
    out = S.what_more_laws_buy(rows, 4000)
    assert out["drawn"] == 1200 and out["budget"] == 4000
    held = next(r for r in out["rare"] if r["class"] == "a lattice held")
    assert held["laws_at_budget"] == round(held["laws_now"] * 4000 / 1200)
    assert held["relative_error_at_budget"] < held["relative_error_now"]
    empty = out["common"][0]
    assert empty["plus_minus_points_at_budget"] < empty["plus_minus_points_now"]
    absence = out["absence"]
    assert absence["from_empty_or_random_a_geometry"] == 0
    assert absence["rarer_than_one_in_now"] == round(absence["laws_read_at_two_sizes"] / 3)


def test_the_kinds_count_the_missing_mass_and_the_halves_compare_what_both_reached(tmp_path):
    rows = L.rows(bundle(tmp_path))
    kinds = S.kinds(rows, 4000)
    assert kinds["kinds"] >= 3 and 0 <= kinds["missing_mass"] < 1 and kinds["chao1"] >= kinds["kinds"]
    assert kinds["expected_at_budget"] >= kinds["kinds"]
    halves = S.halves(rows)
    assert {r["reading"] for r in halves["readings"]} == {"the outcome at 256", "the starts' class at 1,024"}
    assert halves["worst"] < 4, "two halves of one draw agree"


def test_the_cells_say_what_a_claim_needs(tmp_path):
    cells = S.cells(L.rows(bundle(tmp_path)))
    assert cells["pairs"] == 10 and cells["comparisons"] == 10 * S.SCAN_OUTCOMES
    needs = {n["claim"]: n["laws_drawn"] for n in cells["needs"]}
    assert needs["any share to 1 point either way"] == round(3.84 * 0.21 / 0.01 ** 2)
    assert needs["holding 2 times as likely in a pair"] > needs["holding 3 times as likely in a pair"] > needs[
        "holding 5 times as likely in a pair"], "a weaker pattern needs more laws"


def test_a_pattern_in_every_campaign_is_found_and_repeated_and_one_in_half_is_not(tmp_path):
    rows = L.rows(bundle(tmp_path, plant_first_half=True))
    result = P.scan(rows)
    assert result["finding"] == ["1", "2"] and result["checking"] == ["3", "4"]
    by = {(p["outcome"], p["feature"]): p for p in result["patterns"]}
    planted = by[("a lattice held", "degree_neighbor_gradient penalised (coupling > 0)")]
    assert planted["repeated"] and planted["up"] and planted["ratio"] > 2
    half = by.get(("a lattice held", "carries triangle_count"))
    assert half is not None and half["up"] and not half["repeated"], "found in campaigns 1 and 2 alone"
    assert result["repeated"] < result["found"]
    page = P.render({"bundle": "hand", "laws": len(rows), **result})
    assert "degree_neighbor_gradient penalised" in page and "\u2014" not in page


def test_the_criterion_is_read_only_on_the_laws_drawn_after_it(tmp_path):
    rows = L.rows(bundle(tmp_path))
    criterion = {"drawn_after": "2026-10-05T00:00:00Z", "judged_when": {"laws_read_at_least": 10},
                 "predictions": [
                     {"id": "Q1", "claim": "gradient laws hold more", "outcome": "a lattice held",
                      "feature": "degree_neighbor_gradient penalised (coupling > 0)", "rule": {"rate_ratio_at_least": 2}},
                     {"id": "Q2", "claim": "none holds the 4D lattice", "outcome": "the tesseract held",
                      "feature": "zero temperature", "rule": {"positives_at_most": 0}},
                     {"id": "Q3", "claim": "pooled", "pairs": [["an anchor at 8", "the cubic held"]],
                      "rule": {"rate_ratio_at_most": 100}}]}
    out = P.judge(rows, criterion)
    later = sum(1 for r in rows if r["drawn"] > "2026-10-05T00:00:00Z")
    assert out["laws_after"] == later < len(rows) and out["judged"]
    assert [p["verdict"] for p in out["predictions"]] == ["held", "held", "held"]
    waiting = P.judge(rows, {**criterion, "judged_when": {"laws_read_at_least": 10 ** 6}})
    assert all(p["verdict"].startswith("reported, not judged") for p in waiting["predictions"])
    assert "Q1" in P.render_judgement(out)


def test_a_ratio_the_laws_cannot_form_is_nothing_to_measure_not_a_miss(tmp_path):
    at_least, at_most, absence = {"rate_ratio_at_least": 4.0}, {"rate_ratio_at_most": 0.333}, {"positives_at_most": 0}
    never = [0, 16, 0, 153]
    assert P._holds(at_least, never, P._ratio(never)) is None and P._holds(at_most, never, P._ratio(never)) is None
    assert P._holds(absence, never, P._ratio(never)) is True, "an absence is read as it is written"
    nobody = [0, 0, 3, 166]
    assert P._holds(at_least, nobody, P._ratio(nobody)) is None
    only_with = [2, 14, 0, 153]
    assert P._ratio(only_with) is None and P._unbounded(only_with)
    assert P._holds(at_least, only_with, None) is True and P._holds(at_most, only_with, None) is False
    assert P._holds(at_least, [0, 16, 3, 150], 0.0) is False and P._holds(at_most, [0, 16, 3, 150], 0.0) is True
    rows = L.rows(bundle(tmp_path))
    criterion = {"drawn_after": "2026-10-05T00:00:00Z", "judged_when": {"laws_read_at_least": 10},
                 "predictions": [{"id": "Q1", "claim": "an anchor at 8 holds the 4D lattice", "pairs": [
                     ["an anchor at 8", "the tesseract held"]], "rule": {"rate_ratio_at_least": 3.0}}]}
    judged = P.judge(rows, criterion)["predictions"][0]
    assert judged["with_the_outcome"] == 0 and judged["verdict"] == "not judged: nothing to measure"
    waiting = P.judge(rows, {**criterion, "judged_when": {"laws_read_at_least": 10 ** 6}})
    assert waiting["predictions"][0]["verdict"] == "reported, not judged: nothing to measure yet"
    assert "missed" not in P.render_judgement(waiting)
