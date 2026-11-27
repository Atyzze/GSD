from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.operations import dex as D
from graph_scale_dynamics.operations import study_seed

H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}
SCIENCE = {"contract": "gsd-science-contract-2", "sha256": "a" * 64, "engine": "0.840.0"}
OTHER = {"contract": "gsd-science-contract-2", "sha256": "b" * 64, "engine": "0.700.0"}


def _law(beta: float) -> tuple[str, dict]:
    spec = dsl.normalize(dict(H12, dynamics=dict(H12["dynamics"], beta=beta)))
    return dsl.fingerprint(spec), spec


def _gz(path: Path, rows) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _chain(law: str, n: int, seed: int, moves: int, campaign="3") -> dict:
    return {"campaign_id": campaign, "candidate_id": law, "n": n, "seed": seed, "replicate": 0, "chain": "empty",
            "ran": True, "moves": moves, "accepted_moves": moves // 3, "final_edges": n, "peak_edges": n,
            "max_degree": 6, "work_units": moves * 7, "termination": None, "seconds": 1.5,
            "seed_peak_memory_bytes": 60 * 2 ** 20}


def _bundle(root: Path, name: str, study: str, laws, *, science=SCIENCE, seeded=None, chains=()) -> Path:
    folder = root / name
    (folder / "tables").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"study_id": study, "built_utc": "2026-11-26T10:00:00Z",
                                                   "build_number": 880, "science": science}))
    _gz(folder / "tables" / "laws.ndjson.gz",
        [{"campaign_id": campaign, "candidate_id": law, "code": f"S{study}C{campaign}G{i + 1}", "spec": spec,
          "top_n": 65536, "law_score": {"score": score}} for i, (law, spec, score, campaign) in enumerate(laws)])
    _gz(folder / "tables" / "chains.ndjson.gz", chains)
    _gz(folder / "tables" / "rungs.ndjson.gz",
        [{"campaign_id": "3", "candidate_id": law, "n": 1024, "d_s": 2.0} for law, _s, _k, _c in laws])
    (folder / "focus.json").write_text(json.dumps({"contract": "gsd-focus-1", "regions": [], "seeded": seeded or []}))
    return folder


def test_a_bundle_s_scoring_laws_and_the_earlier_study_s_seeds_are_carried_with_their_chains(tmp_path):
    a, a_spec = _law(0.188203)
    b, b_spec = _law(0.3)
    c, c_spec = _law(0.5)
    seeded = [{"bundle": "study_174_x", "study": "174", "science": SCIENCE["sha256"], "selected": True,
               "laws": {c: {"score": 27, "code": "S174C10-06233137"}}}]
    folder = _bundle(tmp_path, "study_176_x", "176", [(a, a_spec, 38, "6"), (b, b_spec, 0, "6"), (c, c_spec, 0, "11")],
                     seeded=seeded, chains=[_chain(a, 1024, 0, 900), _chain(b, 1024, 0, 800), _chain(c, 64, 1, 100)])
    part = D.read_part(folder)
    assert part["kind"] == D.BUNDLE and set(part["laws"]) == {a, c}, "every scoring law, and the earlier study's"
    assert D.standing(part["laws"][c], SCIENCE["sha256"]) == 27 and part["laws"][c]["codes"] == ["S174-C10-06233137"]
    assert {(r["law"], r["n"]) for r in part["chains"]} == {(a, 1024), (c, 64)}, "the chains of the laws it carries"
    dex = D.merge([part], science=SCIENCE, made_by={"study": "177"})
    assert [e["law"] for e in dex["laws"]] == [a, c] and dex["top"] == [a, c]
    path = D.write(dex, tmp_path / "export", "177")
    assert path.name.startswith("dex_177_") and path.name.endswith(".tar.zst")
    back = D.read_part(path)
    assert back["kind"] == D.DEX and set(back["laws"]) == {a, c} and len(back["chains"]) == 2
    view = study_seed.read(path)
    assert [e["law"] for e in view["scoring"]] == [a, c] and view["laws_only"] == []
    assert view["kind"] == D.DEX and view["specs"][a] == a_spec


def test_two_parts_merge_by_law_and_a_score_of_another_science_brings_the_law_alone(tmp_path):
    a, a_spec = _law(0.188203)
    b, b_spec = _law(0.3)
    old = D.read_part(_bundle(tmp_path, "study_170_x", "170", [(a, a_spec, 5, "2"), (b, b_spec, 9, "2")],
                              science=OTHER))
    new = D.read_part(_bundle(tmp_path, "study_176_x", "176", [(a, a_spec, 19, "4")]))
    dex = D.merge([old, new], science=SCIENCE, made_by={"study": "177"})
    entry = {e["law"]: e for e in dex["laws"]}
    assert entry[a]["score"] == 19 and entry[a]["codes"] == ["S170-C2-G1", "S176-C4-G1"]
    assert entry[b]["score"] is None and dex["top"] == [a], "a score read by another science does not stand here"
    assert [e["law"] for e in dex["laws"]] == [a, b]
    view = D.seeding(D.part_of_dex({D.NAME: json.dumps(D.document(dex)).encode()}, "dex_177_x"))
    assert [e["law"] for e in view["scoring"]] == [a] and view["laws_only"] == [b]


def test_a_run_again_agrees_to_the_bit_or_says_where_it_differs():
    a, _spec = _law(0.188203)
    recorded = [dict(_chain(a, 1024, s, 900 + s), law=a, init="empty", source="study_176_x", science="s")
                for s in range(3)]
    again = [dict(_chain(a, 1024, s, 900 + s), law=a, init="empty") for s in range(3)]
    check = D.verify(recorded, again, by="study 177's folder", science="s")[a]
    assert (check["agree"], check["differ"], check["sizes"], check["against"]) == (3, 0, [1024], ["study_176_x"])
    again[1]["final_edges"] += 1
    check = D.verify(recorded, again, by="study 177's folder", science="s")[a]
    assert (check["agree"], check["differ"]) == (2, 1) and check["first_differ"]["final_edges"] == [1024, 1025]
    assert D.verify(recorded, again, by="study 177's folder", science="other") == {}, "another science checks nothing"


def test_a_run_of_another_length_or_from_another_start_is_not_judged():
    a, _spec = _law(0.188203)
    recorded = [dict(_chain(a, 4096, 0, 900), law=a, init="empty", source="study_176_x", science="s"),
                dict(_chain(a, 1024, 0, 500), law=a, init="family_periodic_square_lattice", source="study_176_x",
                     science="s")]
    again = [dict(_chain(a, 4096, 0, 450), law=a, init="empty"),
             dict(_chain(a, 1024, 0, 500), law=a, init="family_random_mean_degree_6"),
             dict(_chain(a, 1024, 1, 700), law=a, init="empty")]
    again[1]["final_edges"] += 7
    assert D.verify(recorded, again, by="study 177's folder", science="s") == {}, (
        "a run half as long, and one from another start, are not the same experiment")
    rows = [dict(r, source="study 177's folder", science="s") for r in again[:1]] + recorded[:1]
    merged = D.merge([{"laws": {}, "chains": rows}], science={"sha256": "s"}, made_by={})
    assert len(merged["chains"]) == 2, "two outcomes of one start are both kept"


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")
def test_a_dex_in_the_import_folder_is_listed_as_a_dex(tmp_path):
    from graph_scale_dynamics.operations import imports
    a, a_spec = _law(0.188203)
    dex = D.merge([D.read_part(_bundle(tmp_path, "study_176_x", "176", [(a, a_spec, 19, "4")]))], science=SCIENCE,
                  made_by={"study": "176"})
    folder = tmp_path / "main" / "import"
    D.write(dex, folder, "176")
    listed = imports.listing(folder, seeded=[], ours=SCIENCE)["bundles"]
    assert len(listed) == 1 and listed[0]["part"] == D.DEX and listed[0]["scoring"] == 1 and listed[0]["science_same"]
    assert D.is_dex_path(next(folder.iterdir()))


def test_a_law_s_code_has_a_dash_between_its_study_campaign_and_graph_and_old_codes_read_the_same():
    from graph_scale_dynamics.operations import law_code as LC
    assert LC.code("178", "11", 4766) == "S178-C11-G4766" and LC.code(None, "3", 7) == "C3-G7"
    assert LC.code("176", "11", None, "a60c2358c5ae") == "S176-C11-a60c2358"
    for old in ("S178C11G4766", "s178-c11-g4766", "S178-C11-G4766"):
        assert LC.same(old, "S178-C11-G4766"), old
    assert LC.upgraded("S176C11G79", "177") == "S176-C11-G79", "an old code keeps its own study"
    assert LC.upgraded("C11-G79", "176") == "S176-C11-G79"
    assert LC.upgraded("S174C2-f8f26f0c", None) == "S174-C2-f8f26f0c"
