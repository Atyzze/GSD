from __future__ import annotations

import gzip
import io
import json
import shutil
import subprocess
import tarfile

import pytest

from graph_scale_dynamics.operations import imports

SCIENCE = {"contract": "gsd-science-1", "sha256": "a" * 64, "probes": "p"}
OTHER = {"contract": "gsd-science-1", "sha256": "b" * 64, "probes": "q"}


def _laws() -> bytes:
    rows = [{"candidate_id": "law1", "campaign_id": "3", "candidate_number": 7, "spec": {"terms": []},
             "law_score": {"score": 19}},
            {"candidate_id": "law2", "campaign_id": "3", "candidate_number": 8, "spec": {"terms": []},
             "law_score": {"score": 0}}]
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb") as handle:
        handle.write("".join(json.dumps(r) + "\n" for r in rows).encode())
    return raw.getvalue()


def _bundle_folder(where, name, science=SCIENCE):
    root = where / name
    (root / "tables").mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"study_id": "174", "build_number": 865,
                                                  "built_utc": "2026-11-25T13:04:19Z", "science": science}))
    (root / "tables" / "laws.ndjson.gz").write_bytes(_laws())
    return root


def _layout(tmp_path):
    folder = tmp_path / "main"
    report_root = folder / "var" / "reports" / "live_campaign_1"
    report_root.mkdir(parents=True)
    return folder, report_root


def test_the_import_folder_sits_beside_var_where_main_py_is(tmp_path):
    folder, report_root = _layout(tmp_path)
    assert imports.folder_of(report_root) == folder / "import"
    assert imports.folder_of(folder / "var" / "reports") == folder / "import"
    assert imports.folder_of(None) is None


def test_the_folder_is_made_and_its_bundles_listed_with_what_they_hold(tmp_path):
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    found = imports.listing(inbox, ours=SCIENCE)
    assert inbox.is_dir() and found["exists"] and found["bundles"] == [], "the folder is made on the first look"
    _bundle_folder(inbox, "study_174_a")
    _bundle_folder(inbox, "study_170_b", science=OTHER)
    (inbox / "notes.txt").write_text("not a bundle")
    (inbox / "half.tar.zst").write_bytes(b"\x28\xb5\x2f\xfd")
    (inbox / ".hidden.tar.zst").write_bytes(b"")
    listed = {b["name"]: b for b in imports.listing(inbox, ours=SCIENCE,
                                                       seeded=[{"bundle": "study_174_a", "at": "2026-11-25T15:20:00Z",
                                                                "laws_added": 1, "regions": []}])["bundles"]}
    assert sorted(listed) == ["half.tar.zst", "study_170_b", "study_174_a"], "every bundle and nothing else"
    first = listed["study_174_a"]
    assert (first["readable"], first["study"], first["build"], first["laws"], first["scoring"], first["kind"]) == (
        True, "174", 865, 2, 1, "folder")
    assert first["science_same"] is True and first["seeded"]["at"] == "2026-11-25T15:20:00Z"
    assert listed["study_170_b"]["science_same"] is False and "probes" in listed["study_170_b"]["science_differ"]
    assert listed["half.tar.zst"]["readable"] is False and listed["half.tar.zst"]["why"]
    assert (folder / "var" / imports.INDEX).is_file(), "what was read is kept in var, not in the import folder"


def test_a_bundle_is_read_once_until_it_changes(tmp_path):
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    root = _bundle_folder(inbox.parent / "import", "study_174_a")
    reads = []

    def reader(path):
        reads.append(path.name)
        return imports.read_one(path)

    imports.listing(inbox, ours=SCIENCE, reader=reader)
    imports.listing(inbox, ours=SCIENCE, reader=reader)
    assert reads == ["study_174_a"]
    (root / "study.json").write_text(json.dumps({"study_id": "174", "build_number": 866, "science": SCIENCE}) + " ")
    assert imports.listing(inbox, ours=SCIENCE, reader=reader)["bundles"][0]["build"] == 866
    assert reads == ["study_174_a", "study_174_a"]


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")
def test_an_archive_as_downloaded_is_listed_by_the_name_it_was_saved_under(tmp_path):
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    inbox.mkdir(parents=True)
    source = _bundle_folder(tmp_path, "study_174_2026-11-25T13-04-19Z")
    tar = tmp_path / "bundle.tar"
    with tarfile.open(tar, "w") as archive:
        archive.add(source, arcname=source.name)
    subprocess.run(["zstd", "-q", "-o", str(inbox / "study_174_2026-11-25T13-04-19Z_tar.zst"), str(tar)], check=True)
    found = imports.listing(inbox, ours=SCIENCE)["bundles"][0]
    assert (found["kind"], found["readable"], found["bundle"], found["scoring"]) == (
        "archive", True, "study_174_2026-11-25T13-04-19Z", 1)


def test_only_a_bundle_in_the_folder_can_be_named(tmp_path):
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    _bundle_folder(inbox, "study_174_a")
    (inbox / "notes.txt").write_text("x")
    assert [p.name for p in imports.named(inbox, ["study_174_a"])] == ["study_174_a"]
    for bad in (["../main"], ["notes.txt"], ["missing.tar.zst"], [""], []):
        with pytest.raises(ValueError):
            imports.named(inbox, bad)
    with pytest.raises(ValueError):
        imports.named(None, ["study_174_a"])


def test_opening_the_folder_asks_the_host_s_file_manager_and_says_so_when_there_is_none(tmp_path, monkeypatch):
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    launched = []
    monkeypatch.setattr(imports, "opener", lambda: ["xdg-open"])
    assert imports.open_folder(inbox, launch=launched.append) == {"opened": str(inbox)}
    assert launched == [["xdg-open", str(inbox)]] and inbox.is_dir()
    monkeypatch.setattr(imports, "opener", lambda: None)
    with pytest.raises(ValueError, match="no file manager"):
        imports.open_folder(inbox, launch=launched.append)


def test_the_ticked_bundles_are_seeded_and_a_refused_one_is_said(tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import study_seed
    folder, report_root = _layout(tmp_path)
    inbox = imports.folder_of(report_root)
    _bundle_folder(inbox, "study_174_a")
    _bundle_folder(inbox, "study_170_b")

    def seed(repo, path):
        if path.name == "study_170_b":
            raise ValueError("another science")
        return {"bundle": path.name}

    monkeypatch.setattr(study_seed, "seed", seed)
    done = imports.seed(None, inbox, ["study_174_a", "study_170_b"])
    assert done["seeded"] == [{"bundle": "study_174_a"}] and done["failed"] == [{"name": "study_170_b", "why": "another science"}]
    with pytest.raises(ValueError, match="another science"):
        imports.seed(None, inbox, ["study_170_b"])


def test_the_map_route_opens_the_folder_and_seeds_the_ticked_beside_the_focus_s_own_actions(tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.services.api import focus_route, study_route
    folder, report_root = _layout(tmp_path)
    monkeypatch.setattr(study_route, "REPORT_ROOT", report_root)
    launched = []
    monkeypatch.setattr(imports, "opener", lambda: ["open"])
    monkeypatch.setattr(imports, "open_folder", lambda where: launched.append(where) or {"opened": str(where)})
    monkeypatch.setattr(imports, "seed", lambda repo, where, names: {"seeded": [{"bundle": n} for n in names], "failed": []})
    monkeypatch.setattr(focus, "act", lambda repo, body: {"ok": True, "did": body["do"], "focus_act": True})
    assert focus_route.act(None, {"do": "open_import"})["opened"] == str(folder / "import")
    assert launched == [folder / "import"]
    assert focus_route.act(None, {"do": "seed", "bundles": ["a"]})["seeded"] == [{"bundle": "a"}]
    assert focus_route.act(None, {"do": "seed", "bundle": "/x"}).get("focus_act"), "a path still reaches the focus's own seed"
    assert focus_route.act(None, {"do": "lean", "focus": 0.5}).get("focus_act")
