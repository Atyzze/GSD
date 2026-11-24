from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.observability import every_chain_graph as G
from graph_scale_dynamics.observability import two_chains as TC
from graph_scale_dynamics.research import structure_reading as SR

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["empty", "random", "square", "cubic", "tesseract"]
KEYS = ["empty", "given", "square", "cubic", "tesseract"]
SIZES = (64, 256)
KINDS = ["return_probability", "volume_growth", "walk_displacement", "box_covering"]


@pytest.fixture(scope="module")
def law_of_five(tmp_path_factory):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    from tests.unit.test_a_designed_study_runs_its_starts import LAW
    from tests.support import designs
    design = designs.of_four_starts()
    design.pop("starts_reading")
    spec = SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][0], 0)
    blobs = tmp_path_factory.mktemp("blobs")
    store = BlobStore(blobs)
    rows = []
    for n in SIZES:
        policy = dict(one_shot_policy(spec, n, fingerprint(LAW), LAW), max_sweeps_multiplier=2)
        for seed in range(2):
            envelope = run_one_shot(LAW, n, seed, one_shot=policy, record_points=40)
            metrics, curves = analyze_one_shot_envelope(envelope, seed=seed)
            digest, _ = store.put_json(json.loads(json.dumps(curves, default=str)))
            rows.append({"n": n, "seed": seed, "curves_artifact": digest,
                         "metrics": json.loads(json.dumps(metrics, default=str))})
    return SimpleNamespace(spec=spec, rows=rows, blobs=blobs, law=LAW)


class _Repo:
    def __init__(self, law):
        self.law = law

    def measurements(self, candidate_id, analysis_version, campaign_id):
        return self.law.rows

    def candidate(self, candidate_id, campaign_id):
        return {"spec": self.law.law}

    def campaign(self, campaign_id):
        return {"spec": self.law.spec}

    def engine_decisions(self, campaign_id, candidate_id):
        return []


def _chains(law):
    return TC.two_chains(law.rows, given_start="the random start", starts=law.spec["sampling_contract"]["given_starts"])


def test_every_chain_is_listed_in_the_campaign_s_order_by_its_start(law_of_five):
    listed = G.listed(_chains(law_of_five))
    assert [c["name"] for c in listed] == NAMES and [c["key"] for c in listed] == KEYS
    assert listed[0]["start"] == "the empty graph" and listed[3]["start"] == "periodic_cubic_quotient"
    two = G.listed({"given_start": "the declared answer, family_torus"})
    assert [(c["key"], c["start"]) for c in two] == [("empty", "the empty graph"),
                                                     ("given", "the declared answer, family_torus")]
    assert G.listed(None, "a random graph")[1]["start"] == "a random graph"


def test_every_chain_s_graph_is_read_by_the_one_reader_at_the_same_sizes(law_of_five):
    reading = G.every_chain(law_of_five.rows, _chains(law_of_five))
    assert reading["contract"] == G.CONTRACT
    assert [c["name"] for c in reading["chains"]] == NAMES, "in the order the campaign lists its starts"
    shared = None
    for chain in reading["chains"]:
        structure = chain["structure"]
        assert structure == SR.law_structure(law_of_five.rows, chain=chain["key"]), chain["name"]
        assert structure["chain"] == chain["key"] and [r["n"] for r in structure["rungs"]] == list(SIZES), chain["name"]
        for rung in structure["rungs"]:
            assert rung["seeds"] == 2 and rung["mean_degree"]["mean"] > 0, (chain["name"], rung["n"])
        assert [r["n"] for r in chain["census"]] == list(SIZES), chain["name"]
        for rung in chain["census"]:
            assert rung["census"]["largest_component_size"]["seeds"] == 2, (chain["name"], rung["n"])
        keys = (sorted(k for k in structure["rungs"][0] if k not in ("half_volume_radius", "local_d_s")),
                sorted(chain["census"][0]["census"]))
        shared = shared or keys
        assert keys == shared, f"{chain['name']} is read in other fields than the chain before it"
    degrees = {c["name"]: c["structure"]["rungs"][0]["mean_degree"]["mean"] for c in reading["chains"]}
    assert len({round(v, 6) for v in degrees.values()}) > 1, "each chain's own graph, not one chain's five times"
    json.dumps(reading, allow_nan=False)


def test_a_chain_s_census_is_its_own_and_a_chain_without_one_has_none():
    def census(size):
        return {"largest_component": {"size": size, "cycle_rank": 1, "spectral_gap": {"value": 0.5},
                                      "diameter": {"lower_bound": 3, "upper_bound": 4}}, "components": {"count": 1}}
    rows = [{"n": 64, "seed": seed, "metrics": {"census": {"empty": census(60), "given": census(50),
                                                           "more_given": {"cubic": census(40)}}}}
            for seed in range(2)]
    sizes = {chain: G.census_rungs(rows, chain)[0]["census"]["largest_component_size"]["mean"]
             for chain in ("empty", "given", "cubic")}
    assert sizes == {"empty": 60.0, "given": 50.0, "cubic": 40.0}
    assert G.census_rungs(rows, "tesseract") == [] and G.census_rungs([], "empty") == []
    assert SR.of_chain({"more_given": {"empty": 1}}, "empty") is None, "a top chain is never read from the list"
    audit = [dict(rows[0], metrics=dict(rows[0]["metrics"], health={"sampler": {"sampler_audit": True}}))]
    assert G.census_rungs(audit, "empty") == [], "a sampler audit's seed is not a reading"


def test_every_chain_s_curves_are_kept_alike_and_thinned(law_of_five):
    from graph_scale_dynamics.services.api import readings_route
    payload = readings_route.curves(_Repo(law_of_five), "1", "law", SIZES[-1], blobs_root=law_of_five.blobs)
    assert payload["contract"] == G.CURVES_CONTRACT and payload["n"] == SIZES[-1] and payload["kinds"] == KINDS
    assert [c["name"] for c in payload["chains"]] == NAMES
    assert [s["seed"] for s in payload["seeds"]] == [0, 1]
    for seed in payload["seeds"]:
        assert list(seed["chains"]) == KEYS, "every chain of the seed kept its curves, in the campaign's order"
        shapes = {key: sorted(kinds) for key, kinds in seed["chains"].items()}
        assert all(shape == shapes["empty"] for shape in shapes.values()), shapes
        for kinds in seed["chains"].values():
            for curve in kinds.values():
                assert len(curve["x"]) == len(curve["y"]) <= G.CURVE_POINTS + 1
                assert curve["x"] or curve["refused"], "a probe that kept no curve says what refused it"
    assert readings_route.curves(_Repo(SimpleNamespace(rows=[], spec={}, law={})), "1", "law", 64) is None
    json.dumps(payload, allow_nan=False)


def test_curves_are_thinned_keep_their_ends_and_leave_out_what_is_no_number():
    long = {"return_probability": {"t": list(range(1, 1001)), "p0": [1.0 / t for t in range(1, 1001)]},
            "volume_growth": {"radii": [1, 2, 3], "mean_ball": [1.0, float("nan"), 9.0]},
            "walk_displacement": {"times": [], "mean_square_displacement": []}}
    refused = {"valid": False, "refusal": "NO_SCALING_WINDOW", "radii_tried": 10}
    kept = G.chain_curves({**long, "chains": {"given": long, "cubic": {"box_covering": {"radii": [1], "box_counts": [8]}},
                                                    "square": {"box_covering": refused}, "tesseract": None}},
                          [{"key": key} for key in KEYS])
    assert list(kept) == ["empty", "given", "square", "cubic"], "a chain that kept no curves is left out, not drawn empty"
    assert kept["square"] == {"box_covering": {"x": [], "y": [], "refused": "NO_SCALING_WINDOW"}}
    assert kept["empty"] == kept["given"], "the chain from empty and a given chain are thinned by the one rule"
    curve = kept["empty"]["return_probability"]
    assert len(curve["x"]) <= G.CURVE_POINTS + 1 and curve["x"][0] == 1 and curve["x"][-1] == 1000
    assert curve["x"] == sorted(curve["x"]) and len(set(curve["x"])) == len(curve["x"])
    assert kept["empty"]["volume_growth"] == {"x": [1, 3], "y": [1.0, 9.0]}
    assert "walk_displacement" not in kept["empty"] and kept["cubic"] == {"box_covering": {"x": [1], "y": [8]}}


def test_a_size_s_curves_name_a_seed_whose_curves_cannot_be_read():
    rows = [{"n": 64, "seed": 1, "curves_artifact": "b", "metrics": {}}, {"n": 64, "seed": 0, "curves_artifact": "a", "metrics": {}},
            {"n": 64, "seed": 2, "curves_artifact": None, "metrics": {}}, {"n": 256, "seed": 0, "curves_artifact": "c", "metrics": {}}]

    def load(digest):
        if digest == "b":
            raise OSError("gone")
        return {"return_probability": {"t": [1, 2], "p0": [0.5, 0.25]}}
    read = G.curves_at(rows, 64, [{"key": "empty", "name": "empty"}], load)
    assert [s["seed"] for s in read["seeds"]] == [0, 1], "the seeds of this size that kept curves, in order"
    assert read["seeds"][0]["chains"]["empty"]["return_probability"] == {"x": [1, 2], "y": [0.5, 0.25]}
    assert read["seeds"][1] == {"seed": 1, "error": "OSError: gone"}


def test_the_law_s_reading_holds_every_chain_and_no_chain_apart(law_of_five):
    from graph_scale_dynamics.services.api import readings_route
    payload = readings_route.structure(_Repo(law_of_five), "1", "law")
    assert [c["name"] for c in payload["every_chain"]["chains"]] == NAMES
    assert not {"structure", "given_structure", "given_probes"} & set(payload), "no chain's reading beside the list"
    json.dumps(payload, allow_nan=False)


class _Served:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def __init__(self, _target=None):
        self.conn = None

    def close(self):
        pass

    def get_flag(self, _key, default=""):
        return default

    def campaign(self, _campaign_id):
        return None

    def active_campaigns(self):
        return []

    def publish_runtime_imports(self, service, **_kwargs):
        return True


def _ask(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("GET", path, headers={"Host": "127.0.0.1"})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    return response.status, json.loads(raw or b"{}")


def test_the_curves_are_served_a_size_at_a_time_and_computed_once(monkeypatch, tmp_path):
    from graph_scale_dynamics.services.api import gate_route, readings_route
    from graph_scale_dynamics.services.api import main as api_main
    from graph_scale_dynamics.services.web import main as web_main
    monkeypatch.setattr(api_main, "Repo", _Served)
    monkeypatch.setattr(readings_route, "Repo", _Served)
    monkeypatch.setattr(gate_route, "Repo", _Served)
    monkeypatch.setattr(readings_route, "BLOBS_ROOT", None)
    asked = []
    monkeypatch.setattr(readings_route, "curves",
                        lambda repo, c, law, n: asked.append((c, law, n)) or ({"n": n} if law != "nobody" else None))
    api = api_main.ThreadingHTTPServer(("127.0.0.1", 0), api_main.build_handler(
        f"folder-schema:{tmp_path.name}", str(tmp_path / "blobs"), "token", 0, snapshot_tmp=tmp_path / "tmp",
        calibration_root=tmp_path / "cal", repository_root=tmp_path, report_root=tmp_path / "reports",
        report_campaign_id="c1"))
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1", allowed_hosts=(),
        base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert readings_route.BLOBS_ROOT == tmp_path / "blobs", "the API gives the route its blobs"
        for _ in range(3):
            assert _ask(web.server_address[1], "/curves-data/c1/law-a/4096") == (200, {"n": 4096})
        assert asked == [("c1", "law-a", 4096)], "a reader that asks again costs one reading"
        assert _ask(api.server_address[1], "/api/curves/c1/law-a/1024") == (200, {"n": 1024})
        assert _ask(web.server_address[1], "/curves-data/c1/nobody/64")[0] == 404
        for path in ("/curves-data/c1/law-a", "/curves-data/c1/law-a/big", "/curves-data/c1/law-a/64/more"):
            assert _ask(web.server_address[1], path)[0] == 404, path
        assert _ask(api.server_address[1], "/api/curves/c1/law-a/big")[0] == 404
        assert len(asked) == 3, "an address that names no size reads nothing"
    finally:
        for server in (api, web):
            server.shutdown()
            server.server_close()
    assert readings_route.handles(["api", "curves", "c1", "law", "64"])
    assert not readings_route.handles(["api", "curves", "c1", "law", "64", "more"])
    assert not readings_route.handles(["api", "structure", "c1", "law", "64"])


node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_page_draws_every_chain_s_graph_and_curves_as_the_reader_writes_them(law_of_five, tmp_path):
    from graph_scale_dynamics.services.api import readings_route
    repo = _Repo(law_of_five)
    payload = {"structure": readings_route.structure(repo, "1", "law"),
               "curves": readings_route.curves(repo, "1", "law", SIZES[-1], blobs_root=law_of_five.blobs)}
    path = tmp_path / "every_chain.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run([node, str(ROOT / "tests/ui/candidate_smoke.js"), str(ROOT / "graph_scale_dynamics/resources/ui")],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "GSD_EVERY_CHAIN_PAYLOAD": str(path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "every chain's graph and curves drawn from the reader's payload" in result.stdout
