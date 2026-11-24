from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import cluster_reading as C  # noqa: E402

COLUMNS = ["n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction", "triangles_per_node",
           "squares_per_node", "kappa"]


def _values(d: float, degree: float, *, sizes=(1024, 4096)) -> dict:
    return {chain: [[n, d, d, d, 2.0, n ** (1 / d), degree, 1.0, 0.0, 0.1, None] for n in sizes]
            for chain in C.CHAINS}


def test_a_law_is_a_vector_of_its_eight_chains_at_1024_and_their_change_to_4096():
    assert C.CHAINS == ("empty", "given", "square", "triangular", "cubic", "bcc", "fcc", "tesseract")
    row = C.features(_values(2.0, 4.0), COLUMNS)
    assert len(row) == len(C.feature_names()) == 8 * 13 + 8 * 9 + 1
    names = dict(zip(C.feature_names(), row, strict=True))
    assert math.isclose(names["empty reach at 1024"], 0.5) and names["reached 4096"] == 1.0
    assert names["random d_s unread at 1024"] == 0.0 and math.isclose(names["empty mean_degree at 1024"], math.log(5))
    assert C.features(_values(2.0, 4.0, sizes=(4096,)), COLUMNS) is None, "a law not read at 1,024 is left out"
    short = dict(zip(C.feature_names(), C.features(_values(2.0, 4.0, sizes=(1024,)), COLUMNS), strict=True))
    assert short["reached 4096"] == 0.0 and short["empty d_s change to 4096"] == 0.0


def test_two_kinds_of_law_fall_in_two_clusters_and_the_classes_are_read_after():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(60):
        d, degree, label = (2.0, 4.0, "holds") if i % 2 else (5.0, 12.0, "forgets")
        values = _values(d + rng.normal(0, 0.02), degree + rng.normal(0, 0.05))
        rows.append({"law": f"{i:064x}", "features": C.features(values, COLUMNS), "class": label, "kind": "none",
                     "fate": "open", "zero_t": bool(i % 3), "fates": {}})
    x, kept = C.matrix(rows)
    found = C.cluster(x)
    labels = found["labels"]
    by_class = {c: {int(k) for r, k in zip(rows, labels, strict=True) if r["class"] == c} for c in ("holds", "forgets")}
    assert not (by_class["holds"] & by_class["forgets"]), "no cluster mixes the two kinds"
    described = C.describe(rows, np.array([r["features"] for r in rows], dtype=float), labels, C.feature_names())
    assert sum(c["laws"] for c in described) == 60 and all(c["mostly"] for c in described)


def test_a_k_at_the_edge_of_the_search_and_the_imputed_probes_are_said():
    assert C.edge_of(4, {4: 0.5, 5: 0.4, 6: 0.3}) == "lowest" and C.edge_of(6, {4: 0.1, 5: 0.2, 6: 0.3}) == "highest"
    assert C.edge_of(5, {4: 0.1, 5: 0.5, 6: 0.3}) is None and C.edge_of(4, {4: 0.5}) is None
    rng = np.random.default_rng(2)
    rows = []
    for i in range(40):
        values = _values(2.0 + rng.normal(0, 0.02) if i % 2 else 5.0, 4.0 if i % 2 else 12.0)
        if i < 10:
            values["given"][0][1] = None
        rows.append({"law": f"{i:064x}", "features": C.features(values, COLUMNS), "class": "holds", "kind": "none",
                     "fate": "open", "zero_t": False, "fates": {}})
    found = C.imputed(rows, C.feature_names())
    assert found["laws_with_a_probe_imputed"] == 10 and found["share_with_a_probe_imputed"] == 0.25
    assert found["share_of_probe_values_imputed"] == round(10 / (40 * 4 * len(C.CHAINS)), 4)
    x, _kept = C.matrix(rows)
    searched = C.cluster(x)
    assert searched["searched"] == [C.K_FROM, C.K_TO] and searched["at_edge"] == C.edge_of(searched["k"],
                                                                                           searched["tried"])
    result = {"bundle": "b", "reading": "r", "laws": 40, "features_used": 3, "k": 4, "silhouette": 0.6,
              "silhouette_by_k": {4: 0.6, 5: 0.5}, "k_searched": [4, 5], "k_at_edge": "lowest", "imputed": found,
              "clusters": [], "classes_across_clusters": {}}
    page = C.render(result)
    assert "The chosen k is the lowest searched (4 to 5)" in page and "a smaller k, which was not tried" in page
    assert "10 laws (25.0%) have a probe imputed on some chain at 1,024" in page
    assert "chosen k is" not in C.render(dict(result, k_at_edge=None))
