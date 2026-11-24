from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.calibration import ledger as L
from graph_scale_dynamics.calibration import ledger_runs as R


def _measure(cell: str, value: float) -> dict:
    return {"kind": L.MEASURE, "cell": cell, "channels": {"d_s": {"valid": True, "value": value}}}


def test_an_appended_ledger_verifies_and_chains_each_line_to_the_one_before(tmp_path):
    path = L.ledger_path(tmp_path, "geometry", "abc")
    first = L.append(path, [_measure("ring:64:0", 1.0), _measure("ring:64:1", 1.01)])
    second = L.append(path, [_measure("ring:128:0", 1.0)])
    assert L.problems(path) == []
    assert first[0]["prev"] == L.genesis("geometry", "abc")
    assert second[0]["prev"] == first[-1]["hash"]
    assert [r["cell"] for r in L.read(path)] == ["ring:64:0", "ring:64:1", "ring:128:0"]


def test_a_rewritten_line_is_found_and_nothing_more_is_appended_to_it(tmp_path):
    path = L.ledger_path(tmp_path, "geometry", "abc")
    L.append(path, [_measure("ring:64:0", 1.0), _measure("ring:64:1", 1.01)])
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["channels"]["d_s"]["value"] = 2.0
    lines[0] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("its hash is not its content's" in p for p in L.problems(path))
    with pytest.raises(L.LedgerError):
        L.append(path, [_measure("ring:128:0", 1.0)])


def test_a_dropped_line_breaks_the_chain(tmp_path):
    path = L.ledger_path(tmp_path, "geometry", "abc")
    L.append(path, [_measure(f"ring:64:{seed}", 1.0) for seed in range(3)])
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert any("does not follow the line before it" in p for p in L.problems(path))


def test_a_cell_is_measured_once_under_a_fingerprint_and_read_again_only_as_an_attestation(tmp_path):
    path = L.ledger_path(tmp_path, "geometry", "abc")
    [held] = L.append(path, [_measure("ring:64:0", 1.0)])
    with pytest.raises(L.LedgerError, match="already measured"):
        L.append(path, [_measure("ring:64:0", 1.0)])
    with pytest.raises(L.LedgerError, match="does not hold"):
        L.append(path, [{"kind": L.ATTEST, "of": "0" * 64}])
    [attested] = L.append(path, [{"kind": L.ATTEST, "of": held["hash"], "agrees": True}])
    assert L.attestations(tmp_path, "geometry", "abc") == {held["hash"]: [attested]}
    assert L.problems(path) == []


def test_another_fingerprint_is_another_file_and_the_first_is_untouched(tmp_path):
    old = L.ledger_path(tmp_path, "geometry", "old")
    L.append(old, [_measure("ring:64:0", 1.0)])
    before = old.read_bytes()
    L.append(L.ledger_path(tmp_path, "geometry", "new"), [_measure("ring:64:0", 1.002)])
    assert old.read_bytes() == before
    assert L.measured(tmp_path, "geometry", "old")["ring:64:0"]["channels"]["d_s"]["value"] == 1.0
    assert L.measured(tmp_path, "geometry", "new")["ring:64:0"]["channels"]["d_s"]["value"] == 1.002


def test_the_root_is_the_set_s_not_the_order_s():
    hashes = [L.record_hash({"cell": str(i)}) for i in range(7)]
    assert L.merkle_root(hashes) == L.merkle_root(list(reversed(hashes))) == L.merkle_root(hashes + hashes[:2])
    assert L.merkle_root(hashes) != L.merkle_root(hashes[:-1])
    assert L.merkle_root([]) == L.EMPTY_ROOT


def test_a_snapshot_names_each_group_s_fingerprint_and_can_be_cut_to_the_cells_a_reading_used(tmp_path):
    L.append(L.ledger_path(tmp_path, "geometry", "g1"), [_measure("ring:64:0", 1.0), _measure("ring:64:1", 1.0)])
    L.append(L.ledger_path(tmp_path, "quantum_walk", "q1"), [_measure("ring:64:0", 2.0)])
    whole = L.snapshot(tmp_path, {"geometry": "g1", "quantum_walk": "q1"})
    cut = L.snapshot(tmp_path, {"geometry": "g1", "quantum_walk": "q1"}, cells=["ring:64:0"])
    assert whole["records"] == 3 and cut["records"] == 2
    assert whole["groups"]["geometry"]["fingerprint"] == "g1"
    assert whole["root"] != cut["root"]
    assert L.snapshot(tmp_path, {"geometry": "g1", "quantum_walk": "q1"}) == whole


def _table(value: float) -> dict:
    cell = {"status": "ok", "family": "periodic_ring", "parameter": 64, "seed": 0, "n": 64,
            "channels": {"d_s": {"valid": True, "value": value}}, "host": "box", "computed_utc": "2026-11-19T00:00:00Z",
            "elapsed_seconds": 0.1}
    return {"analysis_version": "analysis-5.3.0", "estimator_fingerprint": "e639334808716378", "build_number": 801,
            "families": {"periodic_ring": {"family_fingerprint": "f"}},
            "cells": {"periodic_ring:64:0": cell, "periodic_ring:64:1": {"status": "failed"}}}


def test_a_table_is_filed_under_the_fingerprint_that_measured_it_once_and_a_moved_value_is_named(tmp_path):
    first = R.adopt_table(tmp_path, _table(1.0))
    again = R.adopt_table(tmp_path, _table(1.0))
    moved = R.adopt_table(tmp_path, _table(1.1))
    assert first["fingerprint"] == R.table_geometry_fingerprint(_table(1.0))
    assert (first["written"], again["written"], again["already_held"]) == (1, 0, 1)
    assert moved["held_with_other_values"] == ["periodic_ring:64:0"]
    assert len(L.read(L.ledger_path(tmp_path, "geometry", first["fingerprint"]))) == 1


def test_values_hash_ignores_where_and_when_a_cell_was_measured():
    a = {"cell": "x", "family_fingerprint": "f", "channels": {"q": {"valid": True, "value": 1.0}}, "host": "a"}
    b = dict(a, host="b", utc="2026-01-01T00:00:00Z")
    assert R.values_hash(a) == R.values_hash(b)
    assert R.values_hash(a) != R.values_hash(dict(a, channels={"q": {"valid": True, "value": 1.0 + 1e-12}}))


def test_deviation_is_infinite_when_one_reading_refuses():
    read = {"q": {"valid": True, "value": 2.0}}
    assert R.deviation(read, {"q": {"valid": True, "value": 2.0}}) == 0.0
    assert R.deviation(read, {"q": {"valid": True, "value": 2.002}}) == pytest.approx(0.002 / 2.002)
    assert R.deviation(read, {"q": {"valid": False, "value": None}}) == float("inf")
