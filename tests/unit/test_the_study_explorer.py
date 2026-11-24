from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path

from graph_scale_dynamics.reporting import study_explorer as E
from graph_scale_dynamics.research import law_paths as M
from tests.support.explorer_study import write_study

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import study_explorer as tool


def _record(study: Path, index: int = 0) -> dict:
    return json.loads((study / "study.json").read_text())["campaigns"][index]


def _data(page: str) -> dict:
    blob = re.search(r'<script type="application/octet-stream" id="explorer-data" data-encoding="gzip\+base64">'
                     r'([A-Za-z0-9+/=]+)</script>', page)
    assert blob, "the data rides inside the page"
    return json.loads(gzip.decompress(base64.b64decode(blob.group(1))))


def test_every_law_at_every_rung_from_reports_05_and_28(tmp_path):
    study = write_study(tmp_path, laws=12, ledger_only=3)
    record = _record(study)
    part = E.read_part(study / record["bundle"], record)
    laws, rows = part["laws"], part["rows"]
    assert len(laws) == 15 and part["cap"] == 16.0, "report 05's twelve laws, then the ledger's three others"
    assert [law["phenotype"] for law in laws] == ["in report 05"] * 12 + ["report 28 only"] * 3
    keys = [key for key, *_ in E.ROW_FIELDS]
    first = [dict(zip(keys, values, strict=True)) for index, values, _path in rows if index == 0]
    assert [r["n"] for r in first] == [64, 256, 1024, 4096, 16384], "the base block and the extension"
    assert first[0]["d_B"] is None and first[1]["d_B"] is not None, "a probe that did not read is None"
    assert all(r["kappa"] is not None for r in first[:4]), "the ledger's curvature by rung"
    assert first[0]["squares"] is not None and first[4]["squares"] is None, "the census is the base block's"
    assert first[4]["k"] is not None, "the extension's mean degree"
    other = [dict(zip(keys, values, strict=True)) for index, values, _path in rows if index == 12]
    assert [r["n"] for r in other] == [64, 256] and all(r["d_s"] is None and r["k"] for r in other), (
        "a law with no base block: its mean degree and curvature by rung, from the ledger")
    assert laws[12]["fate"] == "empty" and laws[12]["fate_n"] == 256 and laws[0]["terms"], "its fate and its terms"
    assert E.paths(part) == M.law_paths(study / record["bundle"] / "05-phenotypes.json"), (
        "the degree map's reading of report 05, exactly")


def test_the_page_stands_alone_and_carries_its_data(tmp_path):
    study = write_study(tmp_path, laws=20)
    data = tool.read(study)
    page = E.render(data)
    assert page.startswith("<!doctype html>") and f'data-contract="{E.CONTRACT}"' in page
    assert _data(page) == json.loads(json.dumps(data)), "base64 of gzip of the JSON, nothing lost"
    assert E.render(data) == page, "the same data is the same page (gzip without a timestamp)"
    code = page.replace(re.search(r'id="explorer-data"[^>]*>[^<]*<', page).group(0), "")
    for reach in (" src=", "href=\"http", "fetch(", "XMLHttpRequest", "import(", "@import", "url(http", "<link"):
        assert reach not in code, f"the page reaches out ({reach}): it must open from the bundle on disk"
    assert len(data["campaigns"]) == 4 and [c["cap"] for c in data["campaigns"]] == [16.0, 32.0, 16.0, 32.0]
    assert data["campaigns"][0]["zero_temperature"] is True and data["campaigns"][2]["zero_temperature"] is False
    fields = [f["key"] for f in data["row_fields"]]
    assert fields[:6] == ["n", "d_s", "d_V", "d_B", "d_w", "k"] and "given_d_s" not in fields, "a column no law read is left out"
    assert set(data["rows"]) == {"law", *fields} and len(set(map(len, data["rows"].values()))) == 1
    every = [p for c in json.loads((study / "study.json").read_text())["campaigns"]
             for p in M.law_paths(study / c["bundle"] / "05-phenotypes.json")]
    assert data["ceiling"] == E.ceiling(every), "the probe's ceiling over every law's path of report 05"
    assert data["rules"] == {"whole": E.WHOLE, "at_ceiling": E.AT_CEILING,
                             "ceiling_min_laws": E.CEILING_MIN_LAWS}
    assert set(data["families"]) == {"periodic_square_lattice", "periodic_cubic_lattice"}
    square = data["families"]["periodic_square_lattice"]["points"]
    assert [p["n"] for p in square] == [64, 256, 1024] and square[0]["k"] == 4.0 and square[0]["d_s"] == 1.92
    assert data["papers"] == [], "no replication run in the tree since 714; a rerun committed is shown"


def test_the_tool_writes_one_for_a_bundle_without_one(tmp_path, capsys):
    study = write_study(tmp_path, laws=8)
    out = tmp_path / "explorer.html"
    assert tool.main([str(study), "--out", str(out)]) == 0
    assert "4 campaign(s), 52 laws" in capsys.readouterr().out
    data = _data(out.read_text())
    assert data["study"]["study_id"] == "999" and data["title"] == "Study 999: the explorer, 2026-10-03T00:00:00Z"
    table = tmp_path / "table.json"
    table.write_text(json.dumps({"cells": {}}))
    assert tool.main([str(study), "--out", str(out), "--calibration", str(table)]) == 0
    assert _data(out.read_text())["families"] == {}, "--calibration names the table to draw the families from"


def test_an_empty_study_still_has_a_page():
    data = E.document([], title="Study 1: the explorer", study={"study_id": "1"})
    assert data["rows"] == {"law": [], "n": []} and data["laws"] == {}
    assert _data(E.render(data))["rows"]["law"] == []
    assert "could not be made: why" in E.unavailable("t", "why")


def test_the_family_ranking_rides_in_the_bundle_as_fields_of_the_explorer():
    from graph_scale_dynamics.reporting import study_explorer as E
    rows = [key for key, *_ in E.ROW_FIELDS]
    laws = [key for key, *_ in E.LAW_FIELDS]
    assert "family_distance" in rows
    assert {"nearest", "nearest_distance"} <= set(laws)
    assert not {"verdict", "novelty", "limiting"} & set(laws), "the discovery score's fields are gone"
