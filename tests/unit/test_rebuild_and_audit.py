from __future__ import annotations

import pytest

from graph_scale_dynamics.measurements.analysis import CLUSTERING_MAX_N
from graph_scale_dynamics.research.phenotype_rebuild import rebuild_phenotypes
from graph_scale_dynamics.research.stability_score import density_diagnostic

BASE = [64, 256, 1024, 4096, 16384]


class _FakeRepo:
    def __init__(self, summaries_by_candidate, stored=None):
        self._summaries = summaries_by_candidate
        self._stored = dict(stored or {})
        self.written = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def all_campaigns(self):
        return [{"campaign_id": "1", "spec": {
            "ladder": list(BASE),
            "analysis_version": "analysis-3.0.0",
            "base_block": {"contract": "rung-phenotype-3", "sizes": list(BASE)},
            "limits": {"mean_degree_window": {"min": 1.5, "max": 8},
                       "connectivity_floor": 0.9}}}]

    def candidates(self, campaign_id=None):
        return [{"candidate_id": cid} for cid in self._summaries]

    def campaign_analysis_contract(self, campaign_id):
        return "analysis-3.0.0"

    def rung_summaries(self, candidate_id, analysis_version, campaign_id=None):
        return [{"n": n, "summary": s}
                for n, s in sorted(self._summaries[candidate_id].items())]

    def measurements(self, candidate_id, analysis_version, campaign_id=None):
        return [{"n": n, "seed": seed, "metrics": {"health": {"n": n, "rung_terminal": {
                    "classification": "EQUILIBRATED_ACTIVE", "reason": "completed"}}}}
                for n in sorted(self._summaries[candidate_id]) for seed in range(3)]

    def base_block_phenotype(self, candidate_id, analysis_version, campaign_id=None):
        stored = self._stored.get(candidate_id)
        return {"phenotype": stored} if stored is not None else None

    def upsert_base_block_phenotype(self, campaign_id, candidate_id,
                                    analysis_version, contract, phenotype):
        self.written[candidate_id] = phenotype


def _summary(n, d_s=2.0, degree=3.0):
    return {"n": n, "seeds": 3,
            "d_s": {"mean": d_s, "se": 0.09, "n_seeds": 3},
            "d_V": {"mean": None, "n_seeds": 0},
            "d_B": {"mean": None, "n_seeds": 0},
            "d_w": {"mean": None, "n_seeds": 0},
            "mean_degree": {"mean": degree, "se": 0.0, "n_seeds": 3},
            "connected_fraction": {"mean": 1.0, "se": 0.0, "n_seeds": 3},
            "probe_refusals": {"d_V": {"EXPONENTIAL_GROWTH": 3}}}


@pytest.fixture
def patched_repo(monkeypatch):
    def _install(repo):
        monkeypatch.setattr("graph_scale_dynamics.research.phenotype_rebuild.Repo",
                            lambda _db: repo)
        return repo
    return _install


def test_a_deep_law_gains_its_extension_without_apply_writing_anything(patched_repo):
    repo = patched_repo(_FakeRepo({
        "deep": {n: _summary(n) for n in BASE + [65536, 262144]},
        "shallow": {n: _summary(n) for n in BASE},
    }))
    report = rebuild_phenotypes("ignored", apply=False)
    assert report["candidates"] == 2
    assert report["gained_extension"] == 1
    assert report["extension_rungs"] == {"65536,262144": 1}
    assert report["rebuilt"] == 0, "a dry run must not write"
    assert repo.written == {}


def test_apply_writes_and_the_record_carries_the_deep_rungs(patched_repo):
    repo = patched_repo(_FakeRepo({"deep": {n: _summary(n) for n in BASE + [65536]}}))
    report = rebuild_phenotypes("ignored", apply=True)
    assert report["rebuilt"] == 1
    written = repo.written["deep"]
    assert written["extension_sizes"] == [65536]
    assert "top_reading_n" not in written, "read only by the tree line, which left at 790"
    assert written["base_sizes"] == BASE, "the base block is untouched"
    assert written["contract"] == "rung-phenotype-3"


def test_an_identical_rebuild_is_reported_as_unchanged(patched_repo):
    repo = _FakeRepo({"a": {n: _summary(n) for n in BASE}})
    patched_repo(repo)
    first = rebuild_phenotypes("ignored", apply=True)
    assert first["changed"] == 1 and first["unchanged"] == 0

    repo2 = _FakeRepo({"a": {n: _summary(n) for n in BASE}},
                      stored={"a": repo.written["a"]})
    patched_repo(repo2)
    second = rebuild_phenotypes("ignored", apply=False)
    assert second["unchanged"] == 1 and second["changed"] == 0, (
        "a rebuild that changes nothing must say so, or a real change cannot be "
        "seen in the dry run")


def test_an_incomplete_base_block_is_skipped_not_half_built(patched_repo):
    patched_repo(_FakeRepo({"partial": {n: _summary(n) for n in BASE[:3]}}))
    report = rebuild_phenotypes("ignored", apply=True)
    assert report["skipped_incomplete_base_block"] == 1
    assert report["rebuilt"] == 0


def test_a_malformed_summary_makes_a_law_skipped_not_half_built(patched_repo):
    bad = {n: _summary(n) for n in BASE}
    bad[16384] = None
    repo = patched_repo(_FakeRepo({"bad": bad, "good": {n: _summary(n) for n in BASE}}))
    report = rebuild_phenotypes("ignored", apply=True)
    assert report["skipped_incomplete_base_block"] == 1
    assert report["rebuilt"] == 1
    assert set(repo.written) == {"good"}


def test_a_law_that_raises_is_counted_and_the_pass_continues(patched_repo):
    broken = {n: _summary(n) for n in BASE}
    broken[4096] = dict(_summary(4096), mean_degree={"mean": "not-a-number"})
    repo = patched_repo(_FakeRepo({"broken": broken,
                                   "good": {n: _summary(n) for n in BASE}}))
    report = rebuild_phenotypes("ignored", apply=True)
    assert report["rebuilt"] >= 1, "one bad law must never stop the pass"
    assert "good" in repo.written


def test_clustering_reaches_the_deepest_rung_any_campaign_buys():
    assert CLUSTERING_MAX_N >= 262144, (
        "clustering was cut off at 4,096, so it is null on all 22,355 of "
        "campaign 1's laws at N=16,384 and above. It is the observable that "
        "separates a tree-like graph from one with loops, and its absence at "
        "depth is what stops report 27 taking a structural invariant")


def test_every_settling_criterion_is_counted_not_only_the_weakest():
    d = density_diagnostic([2.0, 2.60, 2.95, 2.97, 2.972], BASE)
    assert {"not_flowing", "within_tolerance",
            "decelerating_and_within_tolerance",
            "decelerating_and_within_strict"}.issubset(set(d["criteria"]))
    assert d["settled"] is True and d["flowing"] is False


def test_the_corner_that_looks_settled_at_the_base_block_does_not():
    d = density_diagnostic([2.698, 3.060, 3.325, 3.578, 3.789], BASE)
    assert d["flowing"] is False, "the field the gate acts on admits it"
    assert d["settled"] is False


def test_the_rebuild_reads_each_rung_s_verdict_from_its_measurements(patched_repo):
    repo = patched_repo(_FakeRepo({"law": {n: _summary(n) for n in BASE}}))
    rebuild_phenotypes("ignored", apply=True)
    phenotype = repo.written["law"]
    per_n = phenotype.get("per_n") or {}
    classes = {str((cell or {}).get("rung_terminal_classification")) for cell in per_n.values()}
    assert classes == {"EQUILIBRATED_ACTIVE"}, classes
