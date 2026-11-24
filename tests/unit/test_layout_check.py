from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "graph_scale_dynamics" / "resources" / "ui"
SMOKE = ROOT / "tests" / "ui" / "dashboard_smoke.js"
LAYOUT = ROOT / "tests" / "ui" / "layout_check.js"

node = shutil.which("node")
requires_node = pytest.mark.skipif(node is None, reason="node is not installed")


def _check(ui_dir: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    dump = tmp_path / "tables.json"
    smoke = subprocess.run([node, str(SMOKE), str(ui_dir)], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, GSD_LAYOUT_DUMP=str(dump)))
    assert smoke.returncode == 0 and dump.is_file(), smoke.stdout[-2000:] + smoke.stderr[-2000:]
    result = subprocess.run([node, str(LAYOUT), str(ui_dir), str(dump)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    return result


@requires_node
def test_every_table_the_dashboard_draws_fits_at_the_widths_it_is_read(tmp_path):
    result = _check(UI_DIR, tmp_path)
    assert result.returncode == 0 and result.stdout.startswith("OK"), result.stdout[-6000:] + result.stderr[-2000:]


DENSE = ("<table><thead><tr>" + "".join(f"<th>column {i}</th>" for i in range(10)) + "</tr></thead><tbody>"
         + "".join("<tr>" + "".join(f"<td>{word}</td>" for word in (
             f"law{r}xxxxxxxxxxxxx", "UNRESOLVED_FROM_KNOWN", "periodic_honeycomb_lattice", "16384",
             "DISCOVERY_CANDIDATE", "erdos_renyi_dense", "admissible_coherent", "periodic_cubic_lattice",
             "sierpinski_gasket", "no_metric_structure")) + "</tr>" for r in range(12)) + "</tbody></table>")


@requires_node
def test_the_check_fails_the_rule_that_split_words(tmp_path):
    scratch = tmp_path / "ui"
    shutil.copytree(UI_DIR, scratch)
    css = scratch / "system.css"
    source = css.read_text(encoding="utf-8")
    fixed = "border-bottom:1px solid var(--line);overflow-wrap:break-word}th{position:sticky"
    assert fixed in source, "the cell rule changed; update this test"
    css.write_text(source.replace(fixed, fixed.replace("break-word", "anywhere")), encoding="utf-8")
    dump = tmp_path / "tables.json"
    smoke = subprocess.run([node, str(SMOKE), str(scratch)], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, GSD_LAYOUT_DUMP=str(dump)))
    assert smoke.returncode == 0 and dump.is_file(), smoke.stdout[-2000:] + smoke.stderr[-2000:]
    tables = json.loads(dump.read_text(encoding="utf-8"))
    tables["campaignsBody"] = (tables.get("campaignsBody") or [])[:5] + [DENSE]
    dump.write_text(json.dumps(tables), encoding="utf-8")
    result = subprocess.run([node, str(LAYOUT), str(scratch), str(dump)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode != 0 and "a word split across lines" in result.stdout, result.stdout[-3000:]


@requires_node
def test_the_check_sees_now_researching_split_a_word(tmp_path):
    dump = tmp_path / "tables.json"
    smoke = subprocess.run([node, str(SMOKE), str(UI_DIR)], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, GSD_LAYOUT_DUMP=str(dump)))
    assert smoke.returncode == 0 and dump.is_file(), smoke.stdout[-2000:] + smoke.stderr[-2000:]
    panels = json.loads(dump.read_text(encoding="utf-8"))
    assert "live" in panels, "the smoke harness no longer keeps NOW RESEARCHING for the layout check"
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"live": [html.replace("<wbr>", "") for html in panels["live"]]}), encoding="utf-8")
    scratch = tmp_path / "ui"
    shutil.copytree(UI_DIR, scratch)
    css = scratch / "system.css"
    source = css.read_text(encoding="utf-8")
    fixed = "border-radius: 3px; white-space: nowrap;\n  display: inline-block; }"
    assert fixed in source and "96px 220px 64px 76px" in source, "the badge's rule changed; update this test"
    css.write_text(source.replace(fixed, "border-radius: 3px; }").replace("96px 220px 64px 76px", "96px 220px 52px 76px"),
                   encoding="utf-8")
    result = subprocess.run([node, str(LAYOUT), str(scratch), str(old)], capture_output=True, text=True, timeout=600)
    if result.stdout.startswith("SKIP"):
        pytest.skip(result.stdout.strip())
    assert result.returncode != 0 and "live: a word split across lines: first" in result.stdout, result.stdout[-3000:]
    fixed_result = subprocess.run([node, str(LAYOUT), str(UI_DIR), str(old)], capture_output=True, text=True,
                                  timeout=600)
    assert fixed_result.returncode == 0 and fixed_result.stdout.startswith("OK"), fixed_result.stdout[-3000:]
