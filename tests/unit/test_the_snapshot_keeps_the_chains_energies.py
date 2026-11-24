from __future__ import annotations

import copy
import json
from pathlib import Path

from graph_scale_dynamics.observability.two_chains import chains_per_rung, seed_values
from graph_scale_dynamics.research.snapshot_rows import DESCENT_READ, UNREAD_METRICS_SECTIONS, metrics_read

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = json.loads((ROOT / "tests/fixtures/metrics_documents.json").read_text())["documents"]


def test_the_snapshot_keeps_each_chain_s_final_energy_and_nothing_else_of_the_descent():
    for document in DOCUMENTS:
        kept = metrics_read(copy.deepcopy(document))
        assert not set(UNREAD_METRICS_SECTIONS) & set(kept)
        chains = document["descent"]["chains"]
        assert kept["descent"] == {"chains": {name: {DESCENT_READ: chain[DESCENT_READ]}
                                              for name, chain in chains.items() if DESCENT_READ in chain}}


def test_a_snapshot_row_reads_the_energy_a_database_row_reads():
    document = DOCUMENTS[0]
    n = int(document["health"]["n"]) if document["health"].get("n") else 1024
    for chain in ("empty", "given"):
        assert seed_values(metrics_read(copy.deepcopy(document)), n, chain)["energy_per_node"] == \
            seed_values(copy.deepcopy(document), n, chain)["energy_per_node"]
    assert seed_values(metrics_read(copy.deepcopy(document)), n, "empty")["energy_per_node"] is not None


def test_the_chains_report_28_reads_carry_their_energy_through_the_snapshot():
    rows = [{"candidate_id": "law", "n": int(document["health"].get("n") or 1024), "seed": i,
             "metrics": metrics_read(copy.deepcopy(document))} for i, document in enumerate(DOCUMENTS[:3])]
    chains = chains_per_rung(rows)
    energies = [rung["empty"]["energy_per_node"]["mean"] for rung in chains["rungs"]]
    assert energies and all(value is not None for value in energies)


def test_each_chain_s_accepted_moves_an_edge_reach_the_score_through_the_snapshot_as_from_the_database():
    for document in DOCUMENTS:
        n = int(document["health"].get("n") or 1024)
        kept = metrics_read(copy.deepcopy(document))
        assert set(kept["accepted_moves"]) == set(document["move_accounting"])
        for chain, name in (("empty", None), ("given", None), ("given", "square")):
            moved = seed_values(kept, n, chain, name)["moved"]
            assert moved is not None and moved > 0 and moved == seed_values(copy.deepcopy(document), n, chain, name)["moved"]
    rows = [{"candidate_id": "law", "n": 1024, "seed": i, "metrics": metrics_read(copy.deepcopy(DOCUMENTS[1]))}
            for i in range(3)]
    rung = chains_per_rung(rows, [{"name": "random"}, {"name": "square"}])["rungs"][0]
    one = seed_values(rows[0]["metrics"], 1024, "given", "square")["moved"]
    assert rung["more_given"]["square"]["moved"]["median"] == float(f"{one:.6g}")
    assert seed_values({"census": {"empty": {"edges": 10}}}, 64, "empty")["moved"] is None, "no accounting, no read"
