from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "graph_scale_dynamics" / "resources" / "ui" / "candidate.html"


def _script() -> str:
    page = PAGE.read_text(encoding="utf-8")
    return max(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", page), key=len)


def test_the_page_calls_esc_only_if_it_defines_it():
    script = _script()
    defined = re.search(r"(?:function\s+esc\b|(?:const|let|var)\s+esc\s*=)", script)
    calls = re.findall(r"(?<![\w.$])esc\(", script)
    assert defined or not calls, f"the page calls esc() {len(calls)} time(s) and never defines it"


def test_the_base_block_heading_is_still_drawn():
    assert "'base block, from campaign '+String(lin.source_campaign_id)" in _script()
