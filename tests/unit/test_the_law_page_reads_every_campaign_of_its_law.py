from __future__ import annotations

import json

from tests.unit.test_the_page_reads_every_chain import five_chains

__all__ = ["five_chains"]


def _repo(spec, by_campaign, rungs_by_campaign=None):
    from tests.unit.test_a_designed_study_runs_its_starts import LAW

    class Repo:
        def measurements(self, law, version, campaign_id):
            return [dict(r) for r in by_campaign.get(str(campaign_id), [])]

        def rung_summaries(self, law, version, campaign_id):
            return [dict(r) for r in (rungs_by_campaign or {}).get(str(campaign_id), [])]

        def candidate_campaign_ids(self, law):
            return sorted(by_campaign, key=int)

        def candidate(self, candidate_id, campaign_id):
            return {"spec": LAW}

        def campaign(self, campaign_id):
            return {"spec": spec}

        def engine_decisions(self, campaign_id, law):
            return []
    return Repo()


def test_the_sizes_a_law_read_in_another_campaign_are_drawn_on_its_page_and_its_score_stays_its_own(five_chains):
    from graph_scale_dynamics.services.api import readings_route
    spec, rows = five_chains
    deeper = [dict(r, n=256) for r in rows]
    alone = readings_route.structure(_repo(spec, {"1": rows}), "1", "law")
    both = readings_route.structure(_repo(spec, {"1": rows, "2": rows[:1] + deeper[:1], "3": deeper}), "1", "law")
    assert alone["read_elsewhere"] == [] and [r["n"] for r in alone["chains"]["rungs"]] == [64]
    assert both["read_elsewhere"] == [{"n": 256, "campaign": "3", "rows": 3}], (
        "a size missing here is taken from the campaign with the most readings of it, never one this campaign has")
    assert [r["n"] for r in both["chains"]["rungs"]] == [64, 256], "its curves reach the deeper size"
    assert json.dumps(both["score"], sort_keys=True) == json.dumps(alone["score"], sort_keys=True), (
        "the score on the page reads this campaign's own sizes")
    json.dumps(both, allow_nan=False)


def test_the_rung_table_takes_each_missing_size_from_the_campaign_with_the_most_seeds():
    from graph_scale_dynamics.services.api import law_elsewhere

    def rung(n, seeds):
        return {"n": n, "summary": {"seeds": seeds}, "summary_json": "{}"}
    repo = _repo({}, {"15": [], "13": [], "17": []},
                 {"13": [rung(16384, 3), rung(65536, 3)], "17": [rung(65536, 16), rung(262144, 3)]})
    found = law_elsewhere.rungs(repo, "law", "15", {64, 16384})
    assert [(r["n"], r["read_in"], r["summary"]["seeds"]) for r in found] == [(65536, "17", 16), (262144, "17", 3)]
    assert all("summary_json" not in r for r in found) and found[0]["compute"]["read_in"] == "17"
    assert law_elsewhere.rungs(repo, "law", "15", {16384, 65536, 262144}) == [], "nothing this campaign already holds"
