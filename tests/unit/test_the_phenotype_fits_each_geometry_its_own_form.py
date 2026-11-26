from __future__ import annotations

import json
import statistics
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_TABLE = ROOT / "calibration" / "seed_table.json"


@lru_cache(maxsize=1)
def _reach() -> dict[str, list]:
    cells = json.loads(SEED_TABLE.read_text(encoding="utf-8"))["cells"]
    by: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for cell in cells.values():
        if cell.get("half_volume_radius") is not None:
            by[cell["family"]][int(cell["n"])].append(float(cell["half_volume_radius"]))
    return {family: [(n, statistics.fmean(values), len(values)) for n, values in sorted(sizes.items())]
            for family, sizes in by.items()}


def test_each_geometry_s_reach_takes_the_form_its_geometry_predicts():
    from graph_scale_dynamics.observability import phenotype as P
    rule, wrong = P.rule(), []
    for family, (form, exponent) in rule["known_answers"].items():
        found = P.fit(_reach()[family])
        if found["form"] != form or (exponent is not None and abs(found["b"] - exponent) > rule["exponent_within"]):
            wrong.append((family, form, exponent, found["form"], round(found.get("b") or 0.0, 3)))
    assert len(rule["known_answers"]) >= 20
    assert wrong == [], wrong


def test_a_constant_is_the_fewest_form_and_a_phenotype_is_read_against_those_seen():
    from graph_scale_dynamics.observability import phenotype as P
    flat = P.fit([(256, 3.02, 4), (1024, 2.99, 4), (4096, 3.01, 4), (16384, 3.0, 4)])
    assert flat["form"] == "constant" and abs(flat["a"] - 3.0) < 0.02
    assert P.fit([(256, 3.0, 1), (1024, 3.1, 1)])["form"] is None, "fewer than three sizes describe nothing"
    lattice = P.of_series({"empty": {"reach": _reach()["periodic_square_lattice"],
                                     "d_s": [(n, 2.0, 1) for n in (256, 1024, 4096, 16384)]}})
    expander = P.of_series({"empty": {"reach": _reach()["random_3_regular"]}})
    assert "reach as N^(1/2), d near 2" in P.categories(lattice) and "d_s constant" in P.categories(lattice)
    assert P.categories(expander) == ["reach as log N, an expander or a tree"]
    grown = P.of_series({"random": {"reach": _reach()["periodic_triangular_lattice"],
                                    "d_s": [(n, 2.01, 1) for n in (256, 1024, 4096, 16384)]}})
    assert P.nearest_seen(grown, {"square": lattice, "expander": expander}) == ("square", 1.0)


def test_a_bundle_s_laws_get_their_phenotype_and_the_geometry_they_read_like(tmp_path):
    import gzip
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import phenotype_reading
    bundle = tmp_path / "study_999"
    (bundle / "tables").mkdir(parents=True)
    (bundle / "study.json").write_text("{}", encoding="utf-8")
    square = dict((n, r) for n, r, _ in _reach()["periodic_square_lattice"])
    rungs = [{"campaign_id": "1", "candidate_id": "a", "n": n, "seeds": 3, "half_volume_radius": square[n], "d_s": 2.0}
             for n in (256, 1024, 4096, 16384, 65536)]
    with gzip.open(bundle / "tables" / "rungs.ndjson.gz", "wt", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rungs))
    with gzip.open(bundle / "tables" / "laws.ndjson.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"campaign_id": "1", "candidate_id": "a", "code": "S999C1G1"}) + "\n")
    out = tmp_path / "phenotype.json"
    assert phenotype_reading.main([str(bundle), "--table", str(SEED_TABLE), "--json", str(out)]) == 0
    law = json.loads(out.read_text(encoding="utf-8"))["laws"][0]
    assert "reach as N^(1/2), d near 2" in law["categories"] and law["code"] == "S999C1G1"
    assert law["reads_like"] in {"periodic_square_lattice", "periodic_triangular_lattice", "periodic_honeycomb_lattice"}
