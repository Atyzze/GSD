from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.decisions import evidence
from graph_scale_dynamics.decisions.every_chain import chain_metrics
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements.calibration import erdos_renyi_graph
from graph_scale_dynamics.research import giant_degree as GD
from graph_scale_dynamics.research.stability_score import control_family_match, score_law, score_phenotype
from graph_scale_dynamics.scaleflow.flow import rung_summary
from graph_scale_dynamics.scheduling.base_block import base_sizes

ROOT = Path(__file__).resolve().parents[2]
MEAN_DEGREE = 2.6
LADDER = (1024, 2048, 4096)
SEEDS = (1, 2, 3)
FLOORS = {"d_s": 0.05, "d_V": 0.05, "d_B": 0.05, "d_w": 0.05}


@functools.lru_cache(maxsize=None)
def _er_seed(n: int, seed: int) -> dict:
    count, edges = erdos_renyi_graph(n, MEAN_DEGREE, seed=seed)
    adj = E.build_adjacency(count, edges)
    component = E.largest_component(count, adj)
    health = {"n": count, "mean_degree": 2.0 * len(edges) / count, "connected_fraction": len(component) / count,
              **E.graph_structure_metrics(adj, component)}
    giant_degree = 2.0 * health["largest_component_edges"] / len(component)
    as_d_s_read_it_until_761 = {"valid": True, "d_s": giant_degree - 1.0 + 0.01 * (seed - 2), "se": 0.02}
    return {"health": health, "d_s": as_d_s_read_it_until_761}


def _summaries() -> dict[int, dict]:
    return {n: rung_summary([_er_seed(n, seed) for seed in SEEDS]) for n in LADDER}


def _rows(summaries: dict[int, dict]) -> list[dict]:
    return [{"n": n, "summary": summaries[n]} for n in LADDER]


def test_the_rung_s_giant_degree_is_its_seeds_aggregated_as_the_mean_degree_is():
    seeds = [_er_seed(4096, seed) for seed in SEEDS]
    per_seed = [2.0 * m["health"]["largest_component_edges"]
                / round(m["health"]["connected_fraction"] * m["health"]["n"]) for m in seeds]
    summary = rung_summary(seeds)
    node = summary["giant_mean_degree"]
    assert node["mean"] == pytest.approx(sum(per_seed) / len(per_seed))
    assert node["n_seeds"] == summary["mean_degree"]["n_seeds"] == len(SEEDS)
    assert set(node) == set(summary["mean_degree"])
    old = [{"health": {k: v for k, v in m["health"].items() if k != "largest_component_edges"}, "d_s": m["d_s"]}
           for m in seeds]
    assert rung_summary(old[:1] + seeds[1:])["giant_mean_degree"]["n_seeds"] == len(SEEDS) - 1
    assert rung_summary(old)["giant_mean_degree"] is None
    assert rung_summary(old)["mean_degree"] == summary["mean_degree"]


def test_the_evidence_cells_and_the_phenotype_carry_it_to_the_score():
    spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json")
                      .read_text(encoding="utf-8"))
    base = list(base_sizes(spec))
    deep = [16384, 65536]

    def summary(giant):
        return {"mean_degree": {"mean": 2.6}, "connected_fraction": {"mean": 0.905}, "seeds": 3,
                "d_s": {"mean": 1.86, "se": 0.005}, "d_s_valid_fraction": 1.0, "probe_refusals": {},
                **({"giant_mean_degree": {"mean": giant}} if giant is not None else {})}

    state = {"history": [{"health": {"activity": {}, "equilibration": {"split": {"z": 1.0}}}}],
             "classification": "EQUILIBRATED_ACTIVE", "failures": [], "current_multiplier": 8}
    summaries = {n: summary(2.85) for n in base + deep}
    phenotype = evidence._build_four_rung_phenotype(spec, summaries, {n: dict(state) for n in summaries})
    assert all(phenotype["per_n"][str(n)]["giant_mean_degree"] == 2.85 for n in base)
    assert phenotype["extension_giant_mean_degree_vector"] == [2.85, 2.85]
    assert phenotype["extension_per_n"]["65536"]["giant_mean_degree"] == 2.85
    assert GD.phenotype_giant_degrees(phenotype) == [2.85] * (len(base) + len(deep))
    scored = score_phenotype(phenotype, floors=FLOORS, connectivity_floor=0.5)
    assert "tree_line" not in scored and scored["buckets"]["d_s"] != "ON_BRANCHING_LINE", "the tree line left at 790"

    old = {n: summary(None) for n in base + deep}
    before = evidence._build_four_rung_phenotype(spec, old, {n: dict(state) for n in old})
    assert before["extension_giant_mean_degree_vector"] == [None, None]
    assert score_phenotype(before, floors=FLOORS, connectivity_floor=0.5)["buckets"] == scored["buckets"]


def test_the_control_family_degree_check_reads_the_giant_degree():
    sizes = [1024, 4096, 16384]
    reference = {"erdos_renyi_sparse": {n: {"d_s": {"mean": 1.80, "se": 0.02}} for n in sizes}}
    probes = {"d_s": [1.80, 1.80, 1.80], "d_V": [None] * 3, "d_B": [None] * 3, "d_w": [None] * 3}
    assert control_family_match(probes, [2.40] * 3, sizes, reference)["family"] is None
    scored = score_law(probes, None, floors=FLOORS, sizes=sizes, mean_degree_vector=[2.40] * 3,
                       giant_mean_degree_vector=[2.80] * 3, control_reference=reference)
    assert scored["control_family"]["family"] == "erdos_renyi_sparse"
    assert scored["control_family"]["line_degree"] == GD.GIANT
    old = score_law(probes, None, floors=FLOORS, sizes=sizes, mean_degree_vector=[2.40] * 3,
                    control_reference=reference)
    assert old["control_family"]["family"] is None and old["control_family"]["line_degree"] == GD.WHOLE


def test_a_given_chain_chain_carries_its_giant_s_edges_from_its_census():
    metrics = {"health": {"n": 1000},
               "census": {"given": {"n": 1000, "edges": 1300,
                                      "largest_component": {"size": 900, "edges": 1280}}}}
    health = chain_metrics(metrics, 0, "given")["health"]
    assert health["largest_component_edges"] == 1280 and health["connected_fraction"] == 0.9
    summary = rung_summary([dict(chain_metrics(metrics, 0, "given"), d_s={"valid": False})])
    assert summary["giant_mean_degree"]["mean"] == pytest.approx(2 * 1280 / 900)
    assert summary["mean_degree"]["mean"] == pytest.approx(2.6)
