from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_TABLE = ROOT / "calibration" / "seed_table.json"


@lru_cache(maxsize=1)
def _cells() -> dict:
    return json.loads(SEED_TABLE.read_text(encoding="utf-8"))["cells"]


def _filled(cell: dict, everything: dict) -> dict:
    from graph_scale_dynamics.observability import lexicon as L
    features = L.cell_features(cell)
    for feature, field in (("mean_degree", "mean_degree"), ("giant", "giant_fraction")):
        if features[feature] is None:
            known = [(abs(int(other["n"]) - int(cell["n"])), (other.get("structure") or {}).get(field))
                     for other in everything.values()
                     if other.get("family") == cell.get("family") and (other.get("structure") or {}).get(field) is not None]
            features[feature] = min(known)[1] if known else None
    return features


def test_every_family_of_the_table_reads_nearest_its_own_type_on_seeds_it_was_not_made_from():
    from graph_scale_dynamics.observability import lexicon as L
    rule, cells = L.lexicon(), _cells()
    made = L.profiles(cells, below_seed=rule["held_out_from_seed"])
    families = L.type_of_family()
    assert set(families) == {cell["family"] for cell in cells.values()}, "every family of the table has its type"
    read, wrong = Counter(), []
    for key, cell in cells.items():
        if int(cell["seed"]) < rule["held_out_from_seed"] or int(cell["n"]) < rule["known_answers_from_n"]:
            continue
        found = L.reading(_filled(cell, cells), int(cell["n"]), made)
        read[cell["family"]] += 1
        if found["nearest"] != families[cell["family"]]:
            wrong.append((key, found["nearest"], found["spreads"]))
    assert len(read) >= 25 and sum(read.values()) >= 500, read
    assert wrong == [], f"{len(wrong)} held-out readings nearest another type: {wrong[:10]}"


def test_a_law_reads_its_type_from_its_rung_and_one_near_none_is_a_new_zone():
    from graph_scale_dynamics.observability import lexicon as L
    table = L.profiles(_cells())
    cubic = {"d_s": {"mean": 3.01}, "d_s_valid_fraction": 1.0, "d_V": {"mean": 2.97}, "d_V_valid_fraction": 1.0,
             "d_B": {"mean": 2.80}, "d_B_valid_fraction": 1.0, "d_w": {"mean": 1.94}, "d_w_valid_fraction": 0.9,
             "mean_degree": {"mean": 6.0}, "connected_fraction": {"mean": 1.0}}
    found = L.reading(L.features_of_summary(cubic), 16384, table)
    assert found["type"] == "cubic lattice" and not found["new_zone"], found
    odd = dict(cubic, d_s={"mean": 7.5}, d_V={"mean": 1.2}, mean_degree={"mean": 41.0})
    strange = L.reading(L.features_of_summary(odd), 16384, table)
    assert strange["new_zone"] and strange["type"] is None and strange["nearest"], strange
    row = {"d_s": 3.01, "d_s_valid_fraction": 1.0, "d_V": 2.97, "d_V_valid_fraction": 1.0, "d_B": 2.80,
           "d_B_valid_fraction": 1.0, "d_w": 1.94, "d_w_valid_fraction": 0.9, "mean_degree": 6.0,
           "connected_fraction": 1.0}
    assert L.features_of_rung_row(row) == L.features_of_summary(cubic), "a bundle's row and the folder's summary read alike"
    matrix = L.matrix([{"candidate_id": "a", "n": 16384, "features": L.features_of_rung_row(row)},
                       {"candidate_id": "b", "n": 16384, "features": L.features_of_summary(odd)}], table)
    assert matrix["by_type"] == {"a new zone": 1, "cubic lattice": 1}
    assert set(matrix["laws"][0]["near"]) <= set(L.types()) and len(matrix["laws"][0]["near"]) >= 10


def test_the_reading_tool_writes_a_bundle_s_matrix(tmp_path):
    import gzip
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import lexicon_reading
    bundle = tmp_path / "study_999"
    (bundle / "tables").mkdir(parents=True)
    (bundle / "study.json").write_text("{}", encoding="utf-8")
    laws = [{"campaign_id": "1", "candidate_id": "a", "code": "S999C1G1", "law_score": {"score": 2}},
            {"campaign_id": "1", "candidate_id": "b", "code": "S999C1G2", "law_score": {"score": 0}}]
    rungs = [{"campaign_id": "1", "candidate_id": "a", "n": 4096, "d_s": 1.0, "d_s_valid_fraction": 1.0},
             {"campaign_id": "1", "candidate_id": "a", "n": 16384, "d_s": 3.01, "d_s_valid_fraction": 1.0, "d_V": 2.97,
              "d_V_valid_fraction": 1.0, "d_B": 2.80, "d_B_valid_fraction": 1.0, "d_w": 1.94, "d_w_valid_fraction": 0.9,
              "mean_degree": 6.0, "connected_fraction": 1.0}]
    for name, rows in (("laws.ndjson.gz", laws), ("rungs.ndjson.gz", rungs)):
        with gzip.open(bundle / "tables" / name, "wt", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row) + "\n" for row in rows))
    page, data = tmp_path / "lexicon.md", tmp_path / "lexicon.json"
    assert lexicon_reading.main([str(bundle), "--table", str(SEED_TABLE), "--md", str(page), "--json", str(data)]) == 0
    found = json.loads(data.read_text(encoding="utf-8"))
    assert found["by_type"] == {"cubic lattice": 1, "unread": 1}, found["by_type"]
    assert "| S999C1G1 | 2 | 16384 | cubic lattice |" in page.read_text(encoding="utf-8")
