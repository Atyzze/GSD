from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import cap_reading as CR  # noqa: E402

DESIGN = "graph_scale_dynamics/resources/readings/study_172_design.json"
A, B, C = ("a" * 64, "b" * 64, "c" * 64)


def _table(folder: Path, name: str, rows: list) -> None:
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / "tables" / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _chain(law, n, seed, chain, peak, *, multiplier=1, audit=False, memory=1_000_000):
    return {"campaign_id": "1", "candidate_id": law, "job_id": f"{law[:1]}-{n}-{seed}-{multiplier}-{audit}", "n": n,
            "seed": seed, "replicate": 0, "sweeps_multiplier": multiplier, "audit": audit, "chain": chain,
            "init": chain, "ran": True, "ended_at_cap": peak >= 32, "termination": "completed",
            "final_edges": int(peak * n / 2), "final_mean_degree": peak, "peak_edges": int(peak * n / 2),
            "peak_mean_degree": peak, "max_degree": 40, "seed_peak_memory_bytes": memory, "evidence": "compact"}


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "study_172_x"
    root.mkdir()
    (root / "study.json").write_text(json.dumps({"campaigns": [{"campaign_id": "1", "study_design": {
        "design": DESIGN}}]}), encoding="utf-8")
    rows = []
    for n in (64, 256, 1024):
        for seed in (0, 1, 2):
            rows += [_chain(A, n, seed, "square", 20.0), _chain(A, n, seed, "empty", 0.0),
                     _chain(B, n, seed, "square", 20.0), _chain(B, n, seed, "empty", 5.0),
                     _chain(C, n, seed, "square", 15.0 if (n, seed) == (256, 1) else 20.0, memory=3_000_000)]
    rows.append(_chain(A, 1024, 0, "square", 31.0, audit=True))
    rows.append(_chain(C, 1024, 0, "square", 2.0, multiplier=2))
    _table(root, "chains.ndjson.gz", rows)

    def decision(law, going, stopped=()):
        chains = {name: {"action": "run_next", "rule": "base_block"} for name in going}
        chains.update({name: {"action": "stop", "rule": "empty"} for name in stopped})
        return {"campaign_id": "1", "candidate_id": law, "decision_id": f"d-{law[:1]}", "at_n": 1024,
                "action": "run_next", "rule": "base_block", "facts_json": json.dumps({"chains": chains}),
                "inputs_json": json.dumps({"policy": {"fact_sizes_in_a_row": 3}})}
    _table(root, "decisions.ndjson.gz", [decision(A, ["square"], ["empty"]), decision(B, ["square", "empty"]),
                                         decision(C, ["square"])])
    (root / "finds.json").write_text(json.dumps({"columns": ["n", "mean_degree"], "finds": [
        {"law": A, "control": False, "values": {}, "score": {"score": 10, "d": 2.9,
                                                               "parts": {"lattice": {"chain": "square", "value": 9.0}}}}]}))
    return root


def test_a_cap_holds_back_a_law_only_when_every_chain_still_going_sits_at_it(tmp_path):
    found = CR.read(_bundle(tmp_path), caps=(16.0, 24.0))
    assert found["own_cap"] == 32.0 and found["source"] == CR.PEAKS and found["sizes_in_a_row"] == 3
    sixteen, twenty_four = found["caps"]["16"], found["caps"]["24"]
    assert sixteen["laws_held_back_as_too_dense"] == {"1024": 1}, "A only: B's empty chain goes on, C's seed did not"
    assert twenty_four["laws_held_back_as_too_dense"] == {}
    assert sixteen["scoring_laws_held_back"] == 1
    assert sixteen["scoring_laws"][0]["scoring_chain_reaches_at"] == [64, 256, 1024]
    assert sixteen["chains_reaching_it"]["1024"] == [3, 5] and sixteen["chains_at_it_on_every_seed"]["1024"] == 2, (
        "C's longer chain stands for its seed 0, and an audit for none")
    assert sixteen["laws_with_a_chain_reaching_it"]["256"] == 3
    bands = sixteen["memory_by_densest_chain"]["64"]
    assert list(bands) == ["16 to its cap"] and bands["16 to its cap"]["seeds"] == 9
    assert found["deeper"]["from_n"] == 1024 and found["deeper"]["1048576"]["max_bytes"] == 3_000_000 * 1024
    assert "held back as too dense: N=1,024 1" in CR.render(found)


def test_a_bundle_without_chain_peaks_reads_report_28_s_finals_and_says_so(tmp_path):
    root = _bundle(tmp_path)
    (root / "tables" / "chains.ndjson.gz").unlink()
    part = root / "campaign_1_reports_x"
    part.mkdir()
    values = {"square": [[n, 20.0] for n in (64, 256, 1024)], "empty": [[n, 0.0] for n in (64, 256, 1024)]}
    (part / "28-decision-engine.json").write_text(json.dumps({"body": {
        "every_chain": {"value_columns": ["n", "mean_degree"], "laws": {A: {"values": values}}},
        "seeds": {"columns": ["law", "n", "seed", "peak_memory_bytes"], "laws": [A], "rows": [[0, 1024, 0, 5]]}}}))
    found = CR.read(root, caps=(16.0,))
    assert found["source"] == CR.FINALS and found["caps"]["16"]["laws_held_back_as_too_dense"] == {"1024": 1}
    assert "not seen" in CR.render(found)
