from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_JS = ROOT / "graph_scale_dynamics" / "resources" / "ui" / "system.js"

ABSENT = ["null", "undefined", "''", "NaN"]
PRESENT = {"0": "0 W", "0.4": "0 W", "156.2": "156 W"}


def _formatters() -> str:
    source = SYSTEM_JS.read_text(encoding="utf-8")
    wanted = ("num", "unit", "gib", "pct", "watts", "temp", "gbps", "mbps")
    lines = []
    for name in wanted:
        found = re.search(rf"^\s*const {name} = .*?;$", source, re.MULTILINE)
        assert found, f"{name} is no longer a single-line const in system.js"
        lines.append(found.group(0).strip())
    return "\n".join(lines)


@pytest.fixture(scope="module")
def run_js():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on this host; the formatters need a JS engine to be run")

    def run(script: str):
        done = subprocess.run([node, "-e", _formatters() + "\n" + script],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return run


def test_an_absent_reading_is_a_dash_in_every_unit(run_js):
    values = ", ".join(ABSENT)
    out = run_js(f"""
        const out = {{}};
        for (const [name, f] of Object.entries({{gib, pct, watts, temp, gbps, mbps}}))
            out[name] = [{values}].map(f);
        console.log(JSON.stringify(out));
    """)
    for name, rendered in out.items():
        assert rendered == ["—"] * len(ABSENT), f"{name} turned an absent reading into {rendered}"


def test_a_real_zero_is_still_a_reading(run_js):
    out = run_js("console.log(JSON.stringify("
                 + json.dumps(list(PRESENT)).replace('"', "") .replace("[", "[")
                 + ".map(watts)));")
    assert out == list(PRESENT.values())


def test_a_temperature_beside_a_missing_wattage_reads_the_wattage_as_a_dash(run_js):
    out = run_js("console.log(JSON.stringify(`${temp(87)} · ${watts(null)}`));")
    assert out == "87°C · —", f"the CPU tile still renders a missing wattage as {out!r}"


def test_the_sparkline_drops_absent_points_rather_than_plotting_zero(run_js):
    out = run_js("console.log(JSON.stringify("
                 "[1, null, 2, undefined, 3, ''].map(num).filter(v => v !== null)));")
    assert out == [1, 2, 3]
