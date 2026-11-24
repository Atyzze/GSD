from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "prepare_environment.sh"


def _steps() -> dict[int, str]:
    return {int(n): title for n, title in re.findall(r'^step "(\d+) +([^"]+)"', SCRIPT.read_text(encoding="utf-8"),
                                                       re.M)}


def _section_10() -> dict[int, str]:
    text = (ROOT / "docs" / "agent" / "ENVIRONMENT.md").read_text(encoding="utf-8")
    section = re.split(r"\n## (?!#)", text.split("\n## 10 ", 1)[1], maxsplit=1)[0]
    return {int(n): bold.replace("`", "") for n, bold in re.findall(r"^(\d+)\. \*\*([^*]+)\*\*", section, re.M)}


def test_the_script_is_valid_shell():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_section_10_names_each_step_the_script_has_in_its_order():
    steps, items = _steps(), _section_10()
    assert sorted(steps) == list(range(1, len(steps) + 1)) and len(steps) >= 10, steps
    for number, title in steps.items():
        assert number in items, f"section 10 has no item {number} for the script's step {title!r}"
        assert title.startswith(items[number]), (number, title, items[number])


def test_section_10_says_how_to_start_it_and_how_to_only_check():
    section = (ROOT / "docs" / "agent" / "ENVIRONMENT.md").read_text(encoding="utf-8").split("\n## 10 ", 1)[1]
    assert "setsid nohup ./tools/prepare_environment.sh" in section
    assert "--check" in section and '--check) CHECK=1' in SCRIPT.read_text(encoding="utf-8")
