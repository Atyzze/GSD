from __future__ import annotations

import pytest

from graph_scale_dynamics.calibration.rekey import (
    RECORDED_OUTPUTS, UNRECORDED_OUTPUTS, classify_observables, rekey)


@pytest.fixture
def campaign():
    return {"campaign_id": "1",
            "spec": {"ladder": [64, 256, 1024, 4096, 16384],
                     "base_block": {"contract": "rung-phenotype-3",
                                    "sizes": [64, 256, 1024, 4096, 16384]},
                     "extension_ladder": [65536, 262144]}}


def test_apply_without_justification_refuses_before_running_anything(capsys):
    report = rekey(root="/nonexistent", var="/nonexistent", apply=True)
    assert report["status"] == "REFUSED_NO_JUSTIFICATION"
    assert report["sampled"] == 0, (
        "a missing required argument cost three minutes of verification while a "
        "misspelled flag cost milliseconds; nothing that can refuse on its "
        "arguments may do work first")
    assert "Nothing was run" in capsys.readouterr().out


def test_an_observable_no_cell_records_is_inert():
    claim = classify_observables(["clustering"])
    assert claim["inert"] is True
    assert "clustering" not in RECORDED_OUTPUTS
    assert "clustering" in UNRECORDED_OUTPUTS


def test_an_observable_every_cell_records_is_refused():
    report = rekey(root="/nonexistent", var="/nonexistent",
                   inert_observables=["d_s"], apply=True, justification="x")
    assert report["status"] == "REFUSED_OBSERVABLE_IS_RECORDED"
    assert report["sampled"] == 0


def test_an_unknown_observable_is_refused_rather_than_assumed():
    report = rekey(root="/nonexistent", var="/nonexistent",
                   inert_observables=["something_new"], apply=True, justification="x")
    assert report["status"] == "REFUSED_OBSERVABLE_UNKNOWN", (
        "assuming an unlisted observable is unrecorded would re-stamp a table on "
        "a guess; the safe default is to make someone write it down")


def test_the_cli_exposes_the_claim():
    import main as gsd_main
    args = gsd_main.build_parser().parse_args(
        ["calibration-rekey", "--inert-observable", "clustering", "--apply"])
    assert args.inert_observable == ["clustering"]
