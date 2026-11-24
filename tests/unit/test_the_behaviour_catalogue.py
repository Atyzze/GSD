from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

from graph_scale_dynamics.observability import catalogue as K

ROOT = Path(__file__).resolve().parents[2]
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "still_lattice_criterion_1.json"


def _reader():
    spec = importlib.util.spec_from_file_location("catalogue_reading", ROOT / "tools" / "catalogue_reading.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chain(d=None, degree=None, moved=None, full=False, giant=1.0, reach=None):
    return {"d": d, "mean_degree": degree, "moved": moved, "full": full, "giant": giant, "reach": reach}


def test_the_catalogue_names_each_kind_once_with_what_it_is_how_it_is_read_and_how_it_scores():
    found = K.catalogue()
    assert found["contract"] == K.CONTRACT
    ids = K.kinds()
    assert len(ids) == len(set(ids)) and ids[:4] == ["grown", "small_world", "made", "ring"] and ids[-1] == "unread"
    assert ids.index("frozen") == ids.index("still") - 1
    for entry in found["categories"] + found["not_read_here"]:
        assert all(entry.get(field) for field in ("id", "name", "what", "read", "first_seen")), entry
    assert all(entry.get("score") for entry in found["categories"])
    assert "still" in ids and "lowest" in next(e["score"] for e in found["categories"] if e["id"] == "still")


def test_a_law_is_placed_by_the_first_kind_that_applies():
    empty = _chain(degree=0.0)
    full = _chain(degree=32.0, full=True)
    assert K.kind({"bcc": _chain(3.45, 27.1, 2.0), "fcc": _chain(3.46, 27.0, 2.1), "empty": empty}) == "made"
    assert K.kind({"empty": _chain(1.0, 2.0, 5.0), "given": _chain(1.02, 2.0, 6.0), "bcc": full}) == "ring"
    assert K.kind({"empty": empty, "given": _chain(degree=0.01), "bcc": _chain(degree=0.0)}) == "empty"
    assert K.kind({"empty": empty, "given": full, "bcc": full, "cubic": full}) == "full"
    assert K.kind({"empty": empty, "given": full, "bcc": _chain(3.0, 8.01, 0.001), "cubic": full}) == "still"
    assert K.kind({"empty": empty, "given": full, "bcc": _chain(3.0, 8.0, 0.0), "cubic": full}) == "frozen"
    assert K.kind({"bcc": _chain(3.0, 8.0, 0.0), "cubic": _chain(3.0, 6.0, 0.002)}) == "still"
    assert K.kind({"empty": _chain(1.0, 2.0, 5.0), "bcc": full}, twin_points=3) == "grown"
    assert K.kind({"empty": _chain(1.0, 2.0, 5.0), "bcc": full}, twin_points=2) == "apart"
    assert K.kind({"bcc": _chain(2.6, 8.0, 3.0), "cubic": _chain(2.0, 6.0, 2.0), "empty": empty}) == "rewired"
    assert K.kind({"bcc": _chain(3.5, 12.0, 4.0), "empty": empty}) == "moved"
    assert K.kind({"given": _chain(degree=1.5, giant=0.1), "empty": _chain(degree=1.2, giant=0.2)}) == "broken"
    assert K.kind({"given": _chain(2.0, 3.0, giant=0.9), "empty": _chain(1.0, 1.5, giant=0.9)}) == "apart"
    assert K.kind({}) == "unread" and K.kind({"bcc": _chain()}) == "unread"
    assert K.kind({"empty": _chain(degree=0.5), "given": _chain(degree=0.7)}) == "unread"


def test_a_lattice_is_still_only_at_its_own_degree_below_the_share_of_moves_and_never_full():
    assert K.still("bcc", _chain(3.0, 8.0, 0.05))
    assert not K.still("bcc", _chain(3.0, 8.0, 0.06))
    assert not K.still("bcc", _chain(3.0, 8.5, 0.0))
    assert not K.still("bcc", _chain(3.0, 8.0, 0.0, full=True))
    assert not K.still("given", _chain(3.0, 8.0, 0.0))
    assert not K.still("bcc", _chain(3.0, 8.0, None))
    assert K.frozen("bcc", _chain(3.0, 8.0, 0.0)) and not K.frozen("bcc", _chain(3.0, 8.0, 0.001))


def test_the_criterion_was_committed_on_the_catalogue_s_numbers():
    criterion = json.loads(CRITERION.read_text(encoding="utf-8"))
    rule = K.rule()
    assert {k: criterion["rule"][k] for k in ("still_at_most", "degree_within", "full_share")} == {
        k: rule[k] for k in ("still_at_most", "degree_within", "full_share")}
    assert set(criterion["predictions"]) == {"S1", "S2", "S3"}
    assert criterion["committed_utc"].startswith("2026-11-24")


def _bundle(tmp_path: Path, reach=lambda n, d: 1.0) -> Path:
    columns = ["n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction"]
    still = {"bcc": [[n, 3.0, 3.0, 3.0, 3.0, reach(n, 3.0), 8.0, 1.0] for n in (1024, 4096, 16384)],
             "empty": [[n, None, None, None, None, None, 0.0, 0.0] for n in (1024, 4096, 16384)]}
    made = {"bcc": [[n, 3.4, 3.4, 3.5, 3.5, reach(n, 3.45), 27.0, 1.0] for n in (1024, 4096, 16384)],
            "fcc": [[n, 3.4, 3.5, 3.4, 3.5, reach(n, 3.45), 27.1, 1.0] for n in (1024, 4096, 16384)]}
    folder = tmp_path / "study_x" / "campaign_1_reports_x"
    folder.mkdir(parents=True)
    (folder / "28-decision-engine.json").write_text(json.dumps({"campaign_id": "1", "body": {
        "every_chain": {"value_columns": columns, "laws": {"a" * 64: {"values": still}, "b" * 64: {"values": made}}},
        "laws": [{"candidate_id": "a" * 64, "action": "done", "rule": "ladder_complete", "at_n": 16384}]}}),
        encoding="utf-8")
    tables = folder.parent / "tables"
    tables.mkdir()
    with gzip.open(tables / "chains.ndjson.gz", "wt", encoding="utf-8") as out:
        for law, chains, accepted in (("a" * 64, ("bcc", "empty"), 10), ("b" * 64, ("bcc", "fcc"), 90000)):
            for chain in chains:
                for n in (1024, 4096, 16384):
                    for seed in range(3):
                        edges = 0 if chain == "empty" else 4 * n
                        out.write(json.dumps({"candidate_id": law, "chain": chain, "n": n, "seed": seed,
                                              "accepted_moves": accepted, "final_edges": edges,
                                              "ended_at_cap": False}) + "\n")
    return folder.parent


def test_the_reader_places_every_law_and_says_how_early_each_kind_was_known(tmp_path):
    R = _reader()
    found = R.read(_bundle(tmp_path), scores=False)
    assert found["laws"] == 2 and found["kinds"] == {"made": 1, "still": 1}
    assert found["by_law"]["a" * 64]["kinds"] == {"1024": "still", "4096": "still", "16384": "still"}
    early = found["early"]["1024"]
    assert early["laws"] == 2 and early["held"]["still"] == [1, 1] and early["caught"]["made"] == [1, 1]
    assert found["chains"]["1024"]["still_with_a_deeper_size"] == 1
    assert found["chains"]["4096"]["still_at_every_deeper_size"] == 1
    assert "still lattice" in R.render(found)


def test_the_reader_scores_every_law_in_force_its_still_lattice_lowest(tmp_path):
    R = _reader()
    root = _bundle(tmp_path, reach=lambda n, d: 0.9 * n ** (1.0 / d))
    found = R.read(root)
    rows = {row["law"][:1]: row for row in found["score"]["rows"]}
    assert found["score"]["score"] == "gsd-law-score-9" and found["score"]["still"] == 1
    assert (rows["a"]["score"], rows["a"]["by"], rows["a"]["chain"], rows["a"]["still"]) == (1, "still", "bcc", True)
    assert rows["a"]["kept_score"] > 1, "with no accepted moves read the same chain scores as a kept lattice"
    assert rows["b"]["by"] == "kept" and rows["b"]["score"] == rows["b"]["kept_score"] > 1
    assert [row["law"][:1] for row in found["score"]["rows"]] == ["b", "a"]
    assert "no chain still" in R.render(found)


def test_a_probe_from_a_twin_start_settles_by_its_value_within_the_score_s_margin():
    R = _reader()
    relative = {"d_s": {"16384": 0.06, "65536": 0.1}}
    rows = {4096: {"d_s": 1.10}, 16384: {"d_s": 1.04}, 65536: {"d_s": 1.01}}
    found = R.value_settles({"empty": rows, "bcc": rows}, ["empty", "random", "given"], relative)
    assert found == {16384: {"empty:d_s": 2}, 65536: {"empty:d_s": 3}}
    wide = {4096: {"d_s": 2.0}, 16384: {"d_s": 1.5}, 65536: {"d_s": 1.45}}
    assert R.value_settles({"given": wide}, ["given"], relative) == {65536: {"given:d_s": 2}}


SMALL_WORLD_CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "small_world_criterion_1.json"


def test_a_small_world_is_where_starts_agree_on_a_random_graph_s_reach_and_a_d_that_rises():
    import math
    expected = math.log(4096 / 2) / math.log(26) + 0.63
    assert abs(K.random_reach(4096, 26.0) - expected) < 1e-12 and K.random_reach(4096, 1.9) is None
    h31_before = {"bcc": _chain(3.48, 27.1, 2.0, reach=4.58), "fcc": _chain(3.48, 27.0, 2.0, reach=4.56)}
    h31 = {"bcc": _chain(4.02, 26.0, 2.0, reach=5.98), "fcc": _chain(4.01, 25.9, 2.0, reach=5.97),
           "empty": _chain(degree=0.0)}
    assert K.small_world(h31["bcc"], h31_before["bcc"], 16384)
    assert K.kind(h31, before=h31_before, n=16384) == "small_world"
    assert K.kind(h31) == "made", "without the size before it a law is not judged a small world"
    assert K.kind(h31, before=h31_before, n=1024) == "made", "nothing is called a small world below 4,096"
    steady = {name: dict(chain, d=3.5) for name, chain in h31.items() if name != "empty"}
    assert K.kind(steady, before=h31_before, n=16384) == "made", "a d that does not rise is a space"
    far = {name: dict(chain, reach=chain["reach"] * 2) for name, chain in h31.items() if name != "empty"}
    assert K.kind(far, before=h31_before, n=16384) == "made", "a reach past twice the random graph's is no small world"
    half = dict(h31_before, fcc=_chain(None, 27.0, 2.0))
    assert K.kind(h31, before=half, n=16384) == "small_world", "an agreeing chain not read before is not judged"
    assert not K.small_world(h31["bcc"], None, 16384)


def test_the_small_world_criterion_was_committed_on_the_catalogue_s_numbers_before_any_bundle_after_the_baseline():
    criterion = json.loads(SMALL_WORLD_CRITERION.read_text(encoding="utf-8"))
    rule = K.rule()["small_world"]
    assert {k: criterion["rule"][k] for k in rule if k != "words"} == {k: v for k, v in rule.items() if k != "words"}
    assert set(criterion["predictions"]) == {"W1", "W2", "W3"}
    assert criterion["committed_utc"] > "2026-11-24T14:22:52Z"


def test_the_reader_places_h31_s_shape_a_small_world_at_16384(tmp_path):
    R = _reader()
    columns = ["n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction"]
    world = {name: [[4096, 3.48, 3.48, 3.48, 3.48, 4.58, 27.0, 1.0], [16384, 4.02, 4.02, 4.02, 4.02, 5.98, 26.0, 1.0]]
             for name in ("bcc", "fcc")}
    folder = tmp_path / "study_x" / "campaign_1_reports_x"
    folder.mkdir(parents=True)
    (folder / "28-decision-engine.json").write_text(json.dumps({"campaign_id": "1", "body": {
        "every_chain": {"value_columns": columns, "laws": {"h" * 64: {"values": world}}}}}), encoding="utf-8")
    found = R.read(folder.parent, scores=False)
    assert found["by_law"]["h" * 64]["kinds"] == {"4096": "made", "16384": "small_world"}
    assert found["kinds"] == {"small_world": 1}
