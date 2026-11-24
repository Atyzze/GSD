from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from graph_scale_dynamics.reporting import study_explorer as E
from graph_scale_dynamics.reporting import study_front as F
from graph_scale_dynamics.research import advice as A
from tests.support.explorer_study import calibration_table, write_study

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import study_explorer as tool  # noqa: E402


def _parts(study: Path) -> list[dict]:
    index = json.loads((study / "study.json").read_text())
    return [{"campaign": record, "root": study / record["bundle"],
             "part": E.read_part(study / record["bundle"], record, calibration=calibration_table())}
            for record in index["campaigns"]]


def _view(fragment: str) -> dict:
    assert fragment.startswith("#")
    return json.loads(unquote(fragment[1:]))


def test_every_reason_is_read_from_its_own_report_and_the_strongest_ranks_first(tmp_path):
    study = write_study(tmp_path, laws=24, ledger_only=2, front=True)
    parts = _parts(study)
    laws = [law["candidate_id"] for law in parts[0]["part"]["laws"]]
    anchor, held = laws[4], laws[2]
    anchors = {"anchors": [{"candidate_id": anchor, "campaign_id": "1", "reason": {
        "rule": "operator", "note": "by hand"}}]}
    document = A.advise(parts, anchors=anchors)
    by_id = {row["candidate_id"]: row for row in document["laws"]}
    keys = lambda cid: [r["key"] for r in by_id[cid]["reasons"]]  # noqa: E731
    assert "anchor" in keys(anchor) and "by hand" in by_id[anchor]["reasons"][-1]["text"]
    assert set(A.REASONS) == {"anchor"}, "786: the atlas's and the growth study's reasons left with them; 790 the tree line's"
    ranks = [[A.REASONS[r["key"]][0] for r in row["reasons"]] for row in document["laws"]]
    assert all(a[0] >= b[0] for a, b in zip(ranks, ranks[1:], strict=False)), "ranked by the strongest reason"
    assert [row["rank"] for row in document["laws"]] == list(range(1, len(document["laws"]) + 1))
    assert document["laws_with_a_reason"] >= len(document["laws"]) and document["contract"] == A.CONTRACT
    row = by_id.get(held) or document["laws"][0]
    view = _view(row["explorer"])
    assert view == {"p": "laws", "sel": [row["candidate_id"][:16]]}, "a law opens in the explorer, selected"
    assert A.summary(document)["file"] == "advice.json"


def test_a_lead_holds_beyond_the_degree_at_one_n_and_the_next():
    rng = random.Random(5)
    keys = [key for key, *_ in E.ROW_FIELDS]
    rows = []
    for law in range(120):
        for n in (1024, 4096):
            values = dict.fromkeys(keys)
            k = rng.uniform(3, 6)
            values.update(n=n, k=k, d_s=rng.uniform(1, 4), clustering=rng.uniform(0, 0.3))
            values["d_V"] = values["d_s"] + rng.uniform(-0.05, 0.05)
            rows.append((law, tuple(values[key] for key in keys), None))
    part = {"laws": [{"candidate_id": f"{i:064d}"} for i in range(120)], "rows": rows}
    found = A.leads([{"campaign": {"campaign_id": "1", "quadrant": {"zero_temperature": True}}, "part": part}])
    pairs = {(lead["x"], lead["y"]) for lead in found["leads"]}
    assert ("d_s", "d_V") in pairs, found
    lead = next(x for x in found["leads"] if (x["x"], x["y"]) == ("d_s", "d_V"))
    assert (lead["n"], lead["next_n"], lead["group"]) == (1024, 4096, "zero temperature")
    assert lead["partial"] > 0.9 and lead["next_partial"] > 0.9 and lead["readings"] == 120
    assert ("d_s", "clustering") not in pairs and ("clustering", "d_s") not in pairs, "noise is no lead"
    view = _view(lead["explorer"])
    assert [p["rung"] for p in view["m"]["panels"]] == [1024, 4096] and view["f"] == {"cats": {
        "regime": ["zero temperature"]}}
    assert found["pairs_tried"] > 1


def test_the_front_page_carries_the_findings_the_advice_the_cost_and_every_view(tmp_path):
    study = write_study(tmp_path, laws=24, ledger_only=2, front=True)
    parts = _parts(study)
    index = json.loads((study / "study.json").read_text())
    picked = parts[0]["part"]["laws"][3]["candidate_id"]
    document = A.advise(parts, anchors={"anchors": [{"candidate_id": picked, "campaign_id": "1",
                                                      "reason": {"rule": "operator", "note": "by hand"}}]})
    cost = F.cost_models([{"campaign_id": str(p["campaign"]["campaign_id"]), "label": "x", "root": p["root"]}
                          for p in parts])
    assert cost[0]["model"]["available"] and not cost[1]["model"]["available"]
    classify = F.classify_summary(parts)
    assert classify[0]["placed"] == 24 and sum(classify[0]["nearest"].values()) == 24 and "verdicts" not in classify[0]
    assert classify[0]["separable"] is not None, "the resolving power at the top rung"
    inside = F.render(study={"study_id": "999", "built_utc": "2026-10-03T00:00:00Z", "build_number": 577},
                      campaigns=index["campaigns"], links=F.links_inside({"1": "campaign_1_part"}),
                      advice=document, cost=cost, classify=classify)
    assert inside.startswith("<!doctype html>") and f'data-contract="{F.CONTRACT}"' in inside
    for href in ("explorer.html", "gate_trees.html", "advice.json", "study.json", "campaign_1_part/"):
        assert f'href="{href}"' in inside, href
    assert ".svg" not in inside, "the gate trees are a page since 578, and the Classify maps are the explorer's"
    assert "degree_anchor" in inside and "1.08x" in inside and "1.64x on 42" in inside, "the cost model's table"
    assert "a fit needs at least 12" in inside, "a campaign without one says why"
    assert "laws placed against the calibration families" in inside and "pairs of known families" in inside
    first = document["laws"][0]
    assert f'href="explorer.html{first["explorer"]}"' in inside, "each law links the explorer opened on it"
    for reach in ("<script", " src=", "<link", "fetch("):
        assert reach not in inside, f"the page reaches out ({reach})"
    beside = F.render(study={"study_id": "999", "built_utc": "t", "build_number": 577}, campaigns=[],
                      links=F.links_beside("study_999_t"), advice=document)
    assert 'href="study_999_t.explorer.html"' in beside and 'href="study_999_t.tar.zst"' in beside
    assert 'href="study_999_t.gate_trees.html"' in beside, "the gate trees' page beside the archive (578)"
    assert 'title="inside the archive">study.json<' in beside, "a document inside the archive is named, not linked"
    assert "this page written on build" not in inside
    later = F.render(study={"study_id": "999", "built_utc": "t", "build_number": 574, "page_build": 577},
                     campaigns=[], links={})
    assert "this page written on build 577" in later
    assert "The advice could not be made: why" in F.render(study={}, campaigns=[], links={},
                                                          advice={"unavailable": "why"})


def test_the_tool_writes_all_four_for_a_bundle_without_them(tmp_path, capsys):
    study = write_study(tmp_path, laws=16, ledger_only=2, front=True)
    assert tool.main([str(study)]) == 0
    out = capsys.readouterr().out
    assert "laws with a reason" in out and "index.html" in out and "gate_trees.html" in out
    page = (study / "index.html").read_text()
    assert 'href="explorer.html' in page and (study / "explorer.html").is_file()
    assert 'href="gate_trees.html"' in page and (study / "gate_trees.html").is_file(), "the gate trees' page (578)"
    advice = json.loads((study / "advice.json").read_text())
    assert advice["contract"] == A.CONTRACT
    for match in re.finditer(r'href="([^"#]+)', page):
        assert (study / match.group(1)).exists(), f"the front page links {match.group(1)}, which is not beside it"
    elsewhere = tmp_path / "elsewhere"
    assert tool.main([str(study), "--out-dir", str(elsewhere)]) == 0
    linked = (elsewhere / "index.html").read_text()
    for match in re.finditer(r'href="([^"#]+)', linked):
        assert (elsewhere / match.group(1)).exists(), f"{match.group(1)} is linked and not copied beside the page"
    assert "campaign 1" not in re.findall(r'href="[^"]*"[^>]*>([^<]*)<', linked), "the parts stay in the bundle"
