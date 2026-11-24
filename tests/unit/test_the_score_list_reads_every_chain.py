from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import score_list as S  # noqa: E402

from graph_scale_dynamics.observability import law_score as L  # noqa: E402


def _row(n: int, d: float, walk: float = 2.0) -> list:
    return [n, d, d, d, walk, 0.5 * n ** (1 / d), 4.0, 1.0, 0.0, 1.0, 0.0]


def test_a_bundle_s_report_28_is_scored_again_chain_by_chain(tmp_path):
    law = "a" * 64
    entry = {"top_n": 65536, "given": "random",
             "values": {"empty": [[n, None, None, None, None, 1.0, 0.1, 0.1, 0, 0, 0] for n in (4096, 16384, 65536)],
                        "random": [_row(n, 2.0) for n in (4096, 16384, 65536)],
                        "cubic": [_row(n, 3.0) for n in (4096, 16384, 65536)]},
             "starts_reading": {"fates": {"cubic": ["holds", True]}}}
    folder = tmp_path / "campaign_1_reports_x"
    folder.mkdir()
    (folder / "28-decision-engine.json").write_text(json.dumps({"body": {
        "every_chain": {"laws": {law: entry}},
        "laws": [{"candidate_id": law, "action": "done", "rule": "ladder_complete", "at_n": 65536}],
        "law_ledger": {"rows": [{"candidate_id": law, "spec": {"terms": [
            ["degree_sum", None, 1.0, "one", None], ["wedge_count", None, 0.5, "log_N", None]]}}]}}}))
    found = S.read_report_28(tmp_path)
    assert (found["laws"], found["scored"], found["full_points"]) == (1, 1, 1)
    top = found["list"][0]
    assert (top["score"], top["by"], top["chain"], top["to_n"]) == (57, "random", "random", 65536)
    assert top["decision"] == ["done", "ladder_complete", 65536] and "15 of 15" in top["why"]
    assert top["scales_with_n"] == ["log_N"]
    assert "| `aaaaaaaaaaaa` | 57 | 2 | 4.0 | log_N | random (random) | 15 of 15 | 65,536 |" in S.render(found)


def test_a_control_s_given_start_is_not_called_the_random_start():
    entry = {"top_n": 65536, "given": None, "given_family": "periodic_square_lattice",
             "values": {"empty": [], "given": [_row(n, 2.0) for n in (4096, 16384, 65536)]},
             "starts_reading": {"fates": {}}}
    chains, _five = S.chains_of_report(entry)
    given = next(chain for chain in chains["every_chain"] if chain["key"] == "given")
    assert given["family"] == "periodic_square_lattice" and L.who(given) == "lattice"


def test_a_reading_on_a_piece_under_4096_nodes_is_not_counted():
    def law(giant):
        entry = {"top_n": 65536, "given": "random", "starts_reading": {"fates": {}},
                 "values": {"random": [[n, 2.0, 2.0, 2.0, 2.0, 0.5 * n ** 0.5, 4.0, giant, 0.0, 1.0, 0.0]
                                       for n in (4096, 16384, 65536)]}}
        chains, five = S.chains_of_report(entry)
        return L.score(chains, five, references={})
    whole, dust = law(1.0), law(0.2)
    assert whole["score"] > 0 and whole["points"] == L.POINTS
    assert dust["score"] == 0, "a fifth of the graph is 819 and 3,277 nodes at 4,096 and 16,384: no two sizes count"


def test_a_standing_control_that_scores_is_marked_and_counted_apart(tmp_path):
    law = "c" * 64
    entry = {"top_n": 65536, "given": "random", "starts_reading": {"fates": {}},
             "values": {"random": [_row(n, 2.0) for n in (4096, 16384, 65536)]}}
    for name in ("campaign_1_reports_x", "campaign_2_reports_x"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "28-decision-engine.json").write_text(json.dumps({"body": {
            "every_chain": {"laws": {law if name.startswith("campaign_2") else "d" * 64: entry}}}}))
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": [
        {"campaign_id": "1", "bundle": "campaign_1_reports_x"},
        {"campaign_id": "2", "bundle": "campaign_2_reports_x", "controls": {}}]}))
    found = S.read_report_28(tmp_path)
    marked = {row["law"][0]: row["control"] for row in found["list"]}
    assert marked == {"c": True, "d": False}
    page = S.render(found)
    assert "| `cccccccccccc` (a standing control) | 57 |" in page and "1 of the laws that score are the study's" in page
