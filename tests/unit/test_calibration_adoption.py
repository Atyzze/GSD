from __future__ import annotations

import pytest

from graph_scale_dynamics.calibration import adopt as ADOPT


def _cell(family, n, value, seed=0):
    return {"family": family, "n": n, "seed": seed, "parameter": None, "status": "ok",
            "analysis": ADOPT.FP.analysis_version(None),
            "cell_fingerprint": "stale-digest", "science_fingerprint": "stale-science",
            "channels": {"d_s": {"value": value, "se": value / 100.0, "valid": True}},
            "elapsed_seconds": 0.01}


def _document(fingerprint="old-estimator-digest"):
    return {"estimator_fingerprint": fingerprint, "science_fingerprint": "old-science",
            "cells": {f"{fam}:{n}:{seed}": _cell(fam, n, 2.0 + n / 1000.0, seed)
                      for fam in ("periodic_ring", "uniform_random_tree")
                      for seed, n in enumerate((64, 256, 1024, 4096))}}


def test_a_value_neutral_edit_is_adopted_and_every_cell_restamped(monkeypatch):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint", lambda _: "new-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "new-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: f"fresh:{family}")
    document = _document()
    stored = dict(document["cells"])

    def exact(family, parameter, seed, **kw):
        for cell in stored.values():
            if cell["family"] == family and int(cell["seed"]) == int(seed):
                return {"status": "ok", "n": cell["n"], "elapsed_seconds": 0.01,
                        "channels": {k: dict(v) for k, v in cell["channels"].items()}}
        raise AssertionError("sampled a cell that is not in the table")

    monkeypatch.setattr(ADOPT.CELLS, "measure_cell", exact)
    report = ADOPT.verify_and_adopt(document, sample=2)
    assert report["adopted"] is True, report
    assert report["refused"] == []
    assert document["estimator_fingerprint"] == "new-digest"
    assert all(cell["cell_fingerprint"].startswith("fresh:")
               for cell in document["cells"].values()), (
        "every cell must be re-stamped, not only the sampled ones")
    assert document["origin"]["adopted"] is True
    assert any("re-stamped, not re-run" in line
               for line in document["origin"]["adoption_notices"])


def test_a_real_science_change_is_refused(monkeypatch):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint", lambda _: "new-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "new-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: f"fresh:{family}")
    document = _document()

    def moved(family, parameter, seed, **kw):
        cell = next(c for c in document["cells"].values()
                    if c["family"] == family and int(c["seed"]) == int(seed))
        return {"status": "ok", "n": cell["n"], "elapsed_seconds": 0.01,
                "channels": {"d_s": {"value": 9.99, "se": 0.1, "valid": True}}}

    monkeypatch.setattr(ADOPT.CELLS, "measure_cell", moved)
    report = ADOPT.verify_and_adopt(document, sample=2)
    assert report["adopted"] is False, "a moved measurement must never be adopted"
    assert report["refused"], report
    assert document["estimator_fingerprint"] == "old-estimator-digest", (
        "a refused adoption must leave the table exactly as it was")
    assert "origin" not in document


def test_a_table_already_matching_the_runtime_is_left_alone(monkeypatch):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint", lambda _: "old-estimator-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "stale-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: "stale-digest")
    document = _document()
    report = ADOPT.verify_and_adopt(document)
    assert report["adopted"] is False
    assert report["sampled"] == 0
    assert report["stale_cells"] == 0
    assert any("nothing to adopt" in line for line in report["notices"])


def test_stale_cells_are_adopted_even_when_the_header_still_matches(monkeypatch):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint",
                        lambda _: "old-estimator-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "new-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: f"fresh:{family}")
    document = _document()
    stored = dict(document["cells"])

    def exact(family, parameter, seed, **kw):
        for cell in stored.values():
            if cell["family"] == family and int(cell["seed"]) == int(seed):
                return {"status": "ok", "n": cell["n"], "elapsed_seconds": 0.01,
                        "channels": {k: dict(v) for k, v in cell["channels"].items()}}
        raise AssertionError("unknown cell")

    monkeypatch.setattr(ADOPT.CELLS, "measure_cell", exact)
    report = ADOPT.verify_and_adopt(document, sample=2)
    assert report["stale_cells"] == len(stored), (
        "staleness is a property of the cells, not of the document header")
    assert report["adopted"] is True, (
        f"a matching header must not short-circuit adoption: {report}")
    assert all(cell["science_fingerprint"] == "new-science"
               for cell in document["cells"].values())


def test_the_host_noise_floor_is_measured_not_assumed(monkeypatch):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint", lambda _: "new-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "new-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: f"fresh:{family}")
    document = _document()
    stored = dict(document["cells"])
    jitter = iter([1e-14, -1e-14] * 64)

    def noisy(family, parameter, seed, **kw):
        for cell in stored.values():
            if cell["family"] == family and int(cell["seed"]) == int(seed):
                base = cell["channels"]["d_s"]["value"]
                return {"status": "ok", "n": cell["n"], "elapsed_seconds": 0.01,
                        "channels": {"d_s": {"value": base * (1 + next(jitter)),
                                             "se": cell["channels"]["d_s"]["se"],
                                             "valid": True}}}
        raise AssertionError("unknown cell")

    monkeypatch.setattr(ADOPT.CELLS, "measure_cell", noisy)
    report = ADOPT.verify_and_adopt(document, sample=2)
    assert report["adopted"] is True, (
        f"last-digit arithmetic noise is not a science change: {report}")
    assert report["worst_host_spread"] > 0.0, (
        "the host spread must be measured from the repeated runs, not assumed zero")


@pytest.mark.parametrize("sample", [1, 3])
def test_sampling_depth_does_not_change_the_verdict_on_a_clean_table(monkeypatch, sample):
    monkeypatch.setattr(ADOPT.FP, "estimator_fingerprint", lambda _: "new-digest")
    monkeypatch.setattr(ADOPT.FP, "science_fingerprint", lambda: "new-science")
    monkeypatch.setattr(ADOPT.FP, "cell_fingerprint", lambda family, _: f"fresh:{family}")
    document = _document()
    stored = dict(document["cells"])

    def exact(family, parameter, seed, **kw):
        for cell in stored.values():
            if cell["family"] == family and int(cell["seed"]) == int(seed):
                return {"status": "ok", "n": cell["n"], "elapsed_seconds": 0.01,
                        "channels": {k: dict(v) for k, v in cell["channels"].items()}}
        raise AssertionError("unknown cell")

    monkeypatch.setattr(ADOPT.CELLS, "measure_cell", exact)
    assert ADOPT.verify_and_adopt(document, sample=sample)["adopted"] is True
