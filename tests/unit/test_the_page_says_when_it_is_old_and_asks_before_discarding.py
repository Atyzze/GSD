from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "ui"
SYSTEM = (UI / "system.js").read_text(encoding="utf-8")
APP = (UI / "app.js").read_text(encoding="utf-8")
node = shutil.which("node")


def _freshness(cases: list[tuple[dict | None, int]]) -> list[dict]:
    start = SYSTEM.index("  const STALE_AFTER_MS")
    end = SYSTEM.index("  function showFreshness(")
    script = SYSTEM[start:end] + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(([r, f]) => freshnessOf(r, f))));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_every_poll_reads_one_freshness_from_the_whole_answer():
    states = [r["state"] for r in _freshness([
        ({"pending": False, "stale": False, "source_age_ms": 800}, 0),
        ({"pending": False, "stale": True, "source_age_ms": 900, "last_refresh_error": "TimeoutError"}, 0),
        ({"pending": False, "stale": True, "source_age_ms": 1_800_000}, 0),
        ({"pending": True, "stale": True}, 0),
        (None, 1),
        (None, 2),
    ])]
    assert states == ["fresh", "stale", "stale", "cold", "cold", "offline"]
    old = _freshness([({"pending": False, "source_age_ms": 1_800_000}, 0)])[0]
    assert old["why"] == "the snapshot is 1800 s old"
    paused = _freshness([({"pending": False, "source_age_ms": 14_000, "stale_after_ms": 48_000}, 0),
                         ({"pending": False, "source_age_ms": 50_000, "stale_after_ms": 48_000}, 0),
                         ({"pending": False, "source_age_ms": None}, 0)])
    assert [r["state"] for r in paused] == ["fresh", "stale", "fresh"]


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_clearing_a_law_budget_asks_first_and_a_no_puts_the_number_back():
    start = APP.index("  host.querySelectorAll('[data-budget]')")
    end = APP.index("  host.querySelectorAll('[data-open-campaign]')")
    script = """
const sent = [], asked = [];
let answer = false;
const manageCampaign = async body => { sent.push(body) }, refreshCampaigns = async () => {};
const askFirst = text => { asked.push(text); return answer };
const input = {value: '', defaultValue: '40', dataset: {budget: '7'}};
const host = {querySelectorAll: () => [input]};
""" + APP[start:end] + """
(async () => {
  await input.onchange();
  const refused = {sent: sent.length, value: input.value, asked: asked.length};
  answer = true; input.value = ' ';
  await input.onchange();
  input.value = '30';
  await input.onchange();
  console.log(JSON.stringify({refused, sent, asked: asked.length, text: asked[0]}));
})();
"""
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    seen = json.loads(out.stdout)
    assert seen["refused"] == {"sent": 0, "value": "40", "asked": 1}, "a no sends nothing and puts the number back"
    assert seen["sent"] == [{"action": "budget", "campaign_id": "7", "law_budget": "none"},
                            {"action": "budget", "campaign_id": "7", "law_budget": 30}]
    assert seen["asked"] == 2, "a new number is not asked about"
    assert "law budget of 40" in seen["text"]
