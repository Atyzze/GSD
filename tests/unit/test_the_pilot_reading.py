from __future__ import annotations

import importlib.util
from pathlib import Path

from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("pilot_reading", ROOT / "tools" / "pilot_reading.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
FAMILY = P.SR.NAMED["fcc"]
REFS = {FAMILY: {n: {"start": {"mean_degree": {"mean": 12.0}}} for n in (1024, 4096, 16384, 65536)}}


def _law(degrees, *, d=3.0, chain="fcc", score=20, ended="completed"):
    rows = []
    for n, k in zip((1024, 4096, 16384, 65536), degrees, strict=True):
        cells = dict(n=n, d_s=d, d_V=d, d_B=d, d_w=d, mean_degree=k, giant_fraction=1.0, reach=5.0)
        rows.append([cells.get(name) for name in VALUE_COLUMNS])
    return {"values": {chain: rows}, "score": {"score": score, "chain": chain, "to_n": 65536},
            "seeds": [{"n": 4096, "attempts": 1, "ended": ended} for _ in range(3)], "ledger": {}, "starts": {}}


def test_a_scorer_is_read_as_a_ring_a_frozen_a_reshaped_or_a_thinning_lattice():
    assert P.kind(_law((2.0, 2.0, 2.0, 2.0), d=1.0), REFS) == "a ring"
    assert P.kind(_law((12.0, 12.0, 12.0, 12.0)), REFS) == "no edge changed"
    assert P.kind(_law((11.05, 11.05, 11.05, 11.05)), REFS) == "reshaped the same per node", "an fcc chain held at degree 11.05 at every size"
    thinning = _law((16.0, 12.0 + 2 * 400 / 4096, 12.0 + 2 * 401 / 16384, 12.0 + 2 * 360 / 65536))
    assert P.kind(thinning, REFS) == "thinning", "about 400 edges added at every size"
    assert P.kind(_law((11.05,) * 4, chain="empty"), REFS) == "irregular"
    assert P.kind(_law((11.05,) * 4, score=0), REFS) is None


def test_a_law_is_certified_at_a_size_only_when_every_seed_there_passed():
    assert P.certified_at(_law((12.0,) * 4), 4096)
    assert not P.certified_at(_law((12.0,) * 4, ended="ceiling"), 4096)
    assert not P.certified_at(_law((12.0,) * 4), 16384), "no seed there"
