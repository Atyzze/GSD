from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.reporting.study_bundle import INDEX_NAME, bundles_dir, read_index
from graph_scale_dynamics.services.api import readings_route, study_route


def _bundle(base, stem: str, size: int) -> dict:
    folder = bundles_dir(base)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.tar.zst").write_bytes(b"z" * size)
    (folder / f"{stem}.gate_trees.svg").write_bytes(b"<svg/>")
    (folder / f"{stem}.classify_maps.svg").write_bytes(b"<svg></svg>")
    return {"filename": f"{stem}.tar.zst", "svg": f"{stem}.gate_trees.svg", "maps": f"{stem}.classify_maps.svg",
            "built_utc": stem}


def test_a_listed_bundle_its_gate_trees_and_its_row_are_removed(tmp_path):
    rows = [_bundle(tmp_path, "study_252_2026-09-30T00-34-35Z", 100), _bundle(tmp_path, "study_252_2026-09-26T23-19-00Z", 40)]
    (bundles_dir(tmp_path) / INDEX_NAME).write_text(json.dumps({"bundles": rows}))
    out = study_route.delete(tmp_path, "study_252_2026-09-26T23-19-00Z.tar.zst")
    assert out == {"deleted": "study_252_2026-09-26T23-19-00Z.tar.zst", "freed_bytes": 57, "left": 1}, (
        "the archive, its gate trees and its Classify maps (559)")
    assert [b["filename"] for b in read_index(tmp_path)["bundles"]] == ["study_252_2026-09-30T00-34-35Z.tar.zst"]
    left = sorted(p.name for p in bundles_dir(tmp_path).iterdir())
    assert left == [INDEX_NAME, "study_252_2026-09-30T00-34-35Z.classify_maps.svg",
                    "study_252_2026-09-30T00-34-35Z.gate_trees.svg", "study_252_2026-09-30T00-34-35Z.tar.zst"]


def test_a_bundle_since_578_goes_with_its_pages(tmp_path):
    folder = bundles_dir(tmp_path)
    folder.mkdir(parents=True)
    stem = "study_252_2026-10-03T12-40-00Z"
    sizes = {"tar.zst": 30, "explorer.html": 7, "gate_trees.html": 5, "index.html": 3, "advice.json": 2}
    for suffix, size in sizes.items():
        (folder / f"{stem}.{suffix}").write_bytes(b"x" * size)
    row = {"filename": f"{stem}.tar.zst", "explorer": f"{stem}.explorer.html", "gates": f"{stem}.gate_trees.html",
           "front": f"{stem}.index.html", "advice": f"{stem}.advice.json", "built_utc": stem}
    keep = _bundle(tmp_path, "study_252_2026-09-30T00-34-35Z", 100)
    (folder / INDEX_NAME).write_text(json.dumps({"bundles": [row, keep]}))
    out = study_route.delete(tmp_path, f"{stem}.tar.zst")
    assert out == {"deleted": f"{stem}.tar.zst", "freed_bytes": sum(sizes.values()), "left": 1}
    assert not [p for p in folder.iterdir() if p.name.startswith(stem)], "every file beside it goes"
    assert (folder / "study_252_2026-09-30T00-34-35Z.gate_trees.svg").is_file(), "another bundle's picture stays"


def test_its_explorer_goes_with_it(tmp_path):
    row = _bundle(tmp_path, "study_253_x", 10)
    (bundles_dir(tmp_path) / "study_253_x.explorer.html").write_bytes(b"<!doctype html>")
    row["explorer"] = "study_253_x.explorer.html"
    (bundles_dir(tmp_path) / INDEX_NAME).write_text(json.dumps({"bundles": [row]}))
    assert study_route.delete(tmp_path, "study_253_x.tar.zst")["freed_bytes"] == 10 + 6 + 11 + 15
    assert sorted(p.name for p in bundles_dir(tmp_path).iterdir()) == [INDEX_NAME]


def test_its_front_page_and_advice_go_with_it(tmp_path):
    row = _bundle(tmp_path, "study_253_y", 10)
    (bundles_dir(tmp_path) / "study_253_y.index.html").write_bytes(b"<!doctype html>")
    (bundles_dir(tmp_path) / "study_253_y.advice.json").write_bytes(b"{}")
    row.update(front="study_253_y.index.html", advice="study_253_y.advice.json")
    (bundles_dir(tmp_path) / INDEX_NAME).write_text(json.dumps({"bundles": [row]}))
    assert study_route.delete(tmp_path, "study_253_y.tar.zst")["freed_bytes"] == 10 + 6 + 11 + 15 + 2
    assert sorted(p.name for p in bundles_dir(tmp_path).iterdir()) == [INDEX_NAME]


def test_only_a_file_the_index_lists_can_be_deleted(tmp_path):
    rows = [_bundle(tmp_path, "study_252_x", 10)]
    (bundles_dir(tmp_path) / INDEX_NAME).write_text(json.dumps({"bundles": rows}))
    (tmp_path / "keep.txt").write_text("the folder's own file")
    for name in ("not_listed.tar.zst", "../keep.txt", "", INDEX_NAME):
        with pytest.raises(KeyError):
            study_route.delete(tmp_path, name)
    assert (tmp_path / "keep.txt").is_file() and (bundles_dir(tmp_path) / "study_252_x.tar.zst").is_file()


def test_the_route_is_the_admin_only_readings_dispatch(tmp_path, monkeypatch):
    from graph_scale_dynamics.services.api import main as api_main
    assert readings_route.handles(["api", "study-bundles", "delete"])
    monkeypatch.setattr(readings_route.study_route, "REPORT_ROOT", readings_route.study_route.REPORT_ROOT)
    api_main.build_handler("unused", str(tmp_path), "t", 0, report_root=tmp_path / "var")
    assert readings_route.study_route.REPORT_ROOT == (tmp_path / "var").resolve()
