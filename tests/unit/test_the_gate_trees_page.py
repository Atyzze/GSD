from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.reporting import gate_trees_page as P
from graph_scale_dynamics.reporting import study_explorer as E
from graph_scale_dynamics.research import gate_tree as GT
from tests.support.explorer_study import write_study

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests" / "ui" / "gate_trees_check.js"
sys.path.insert(0, str(ROOT / "tools"))

node = shutil.which("node")


def _payload(page: str) -> dict:
    found = re.search(r'<script type="application/json" id="gate-trees-data">(.*?)</script>', page, re.S)
    assert found, "the page carries its data"
    return json.loads(found.group(1))


def test_the_page_carries_every_campaign_s_tree_the_rules_and_the_laws_by_their_fate(tmp_path):
    study = write_study(tmp_path, laws=12, ledger_only=3, front=True)
    index = json.loads((study / "study.json").read_text())
    columns, fates, carried = [], {}, []
    for record in index["campaigns"]:
        part = study / record["bundle"]
        tree = json.loads((part / "28-decision-engine.json").read_text())["body"]["gate_tree"]
        columns.append({"campaign_id": record["campaign_id"], "label": E.label_of(record), "tree": tree,
                        "subtitle": "a made-up campaign"})
        fates[record["campaign_id"]] = P.fates(E.read_part(part, record))
        carried.append(record["campaign_id"])
    data = P.document(columns, title="Study 999: the gate trees", study={"study_id": "999"},
                      explorer_index={cid: i for i, cid in enumerate(carried)}, fate_counts=fates)
    assert data["contract"] == P.CONTRACT and [c["id"] for c in data["campaigns"]] == ["1", "2", "3", "4"]
    first = data["campaigns"][0]
    assert first["explorer"] == 0 and first["fates"] == {"base_block|4096": 12, "empty|256": 3}, (
        "each law counted once, by the rule of its last decision and its rung, as the explorer filters them")
    by_n = {r["n"]: r for r in first["tree"]["rungs"]}
    assert by_n[256]["stopped"] == {"empty": 3} == {"empty": first["fates"]["empty|256"]}, (
        "a gate's stops at a rung are the laws whose fate is that gate at that rung")
    assert data["rules"]["empty"]["kind"] == "gate" and data["rules"]["empty"]["stage"] == "final verdict"
    assert data["rules"]["base_block"]["kind"] == "stream", "the streams that buy a rung are said too"
    assert data["gate_order"] == [gate.name for gate in G.GATES]
    assert data["costs"] == [GT.CHEAP, GT.DEEP], "report 28 sorts the salt's keys; the page reads them by name"
    keys = [c["key"] for c in data["categories"]]
    assert keys[:3] == ["on", "done", "held"] and keys.index("final verdict") > keys.index("structure")
    assert data["stretch_from"] == 65536 and data["reading"], "542's stretch, and report 28's own reading"
    page = P.render(data, links={"explorer": "explorer.html", "front": "index.html"})
    assert page.startswith("<!doctype html>") and f'data-contract="{P.CONTRACT}"' in page
    assert _payload(page)["links"] == {"explorer": "explorer.html", "front": "index.html"}
    for reach in (" src=", "<link", "fetch(", "XMLHttpRequest"):
        assert reach not in page, f"the page reaches out ({reach})"
    for key, _label, light, dark in P.CATEGORIES:
        assert f"--cat-{P.slug(key)}:{light};" in page and f"--cat-{P.slug(key)}:{dark};" in page, key


def test_a_label_that_closes_a_script_cannot_break_out_of_the_page():
    data = P.document([{"campaign_id": "1", "label": "</script><script>alert(1)</script>", "tree": None}],
                      title="t", study={})
    page = P.render(data, links={"explorer": None, "front": None})
    assert "</script><script>alert(1)" not in page
    assert _payload(page)["campaigns"][0]["label"] == "</script><script>alert(1)</script>"
    assert "could not be drawn: why" in P.unavailable("Study 1", "why")


def test_the_tool_writes_the_page_beside_the_explorer_for_a_bundle_without_one(tmp_path, capsys):
    import study_explorer as tool
    study = write_study(tmp_path, laws=10, ledger_only=2, front=True)
    assert tool.main([str(study)]) == 0
    assert "gate_trees.html" in capsys.readouterr().out
    page = (study / "gate_trees.html").read_text()
    data = _payload(page)
    assert data["links"] == {"explorer": "explorer.html", "front": "index.html"}
    assert [c["explorer"] for c in data["campaigns"]] == [0, 1, 2, 3], "every part the explorer carries, in order"
    assert data["campaigns"][0]["tree"]["rungs"][0]["n"] == 64
    front = (study / "index.html").read_text()
    assert 'href="gate_trees.html"' in front and ".svg" not in front, "the front page links the page, no picture"


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_page_draws_opens_and_links_the_explorer_in_a_browser(tmp_path):
    import study_explorer as tool
    study = write_study(tmp_path, laws=30, ledger_only=6, seed=4, front=True)
    assert tool.main([str(study)]) == 0
    result = subprocess.run([node, str(CHECK), str(study / "gate_trees.html")], capture_output=True, text=True,
                            timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0 and result.stdout.startswith("OK"), result.stdout[-4000:] + result.stderr[-2000:]


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_check_fails_a_page_that_breaks(tmp_path):
    import study_explorer as tool
    study = write_study(tmp_path, laws=12, ledger_only=3, seed=2, front=True)
    assert tool.main([str(study)]) == 0
    page = study / "gate_trees.html"
    text = page.read_text()
    assert "function pageGates() {" in text, "the page changed; update this test"
    page.write_text(text.replace("function pageGates() {", "function pageGates() { throw new Error('broken');"))
    result = subprocess.run([node, str(CHECK), str(page)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode != 0 and "an error in the page: broken" in result.stdout, result.stdout[-3000:]
