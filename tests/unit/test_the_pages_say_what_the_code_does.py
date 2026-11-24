from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "docs" / "TOOLS.md"
PAGES = ("docs/TOOLS.md", "docs/OPERATIONS.md", "docs/agent/NEXT_BUILD.md", "docs/agent/ENVIRONMENT.md",
         "docs/agent/HANDOFF.md", "README.md")
COMMAND = re.compile(r"tools/([a-z0-9_]+\.py)((?:[ \t]+[^\s`|]+)*)")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


def test_every_tool_has_its_section_and_every_section_its_tool():
    sections = re.findall(r"^## tools/(\S+)$", TOOLS.read_text(encoding="utf-8"), re.MULTILINE)
    files = sorted(p.name for p in (ROOT / "tools").iterdir() if p.suffix in (".py", ".sh") and p.name != "__init__.py")
    assert sorted(set(files) - set(sections)) == [], "a tool docs/TOOLS.md does not describe"
    assert sorted(set(sections) - set(files)) == [], "a section of docs/TOOLS.md for a tool that is gone"
    assert len(sections) == len(set(sections)), "a tool described twice"


def test_every_option_a_page_writes_is_one_its_tool_takes():
    wrong = []
    for page in PAGES:
        for number, line in enumerate((ROOT / page).read_text(encoding="utf-8").splitlines(), 1):
            for found in COMMAND.finditer(line):
                source = ROOT / "tools" / found.group(1)
                if not source.is_file():
                    wrong.append(f"{page}:{number}: tools/{found.group(1)} does not exist")
                    continue
                code = source.read_text(encoding="utf-8")
                wrong += [f"{page}:{number}: tools/{found.group(1)} takes no {flag}"
                          for flag in FLAG.findall(found.group(2)) if f'"{flag}"' not in code and f"'{flag}'" not in code]
    assert wrong == []


def test_every_rule_the_engine_records_is_named_on_the_decisions_page_and_the_table_names_no_other():
    from graph_scale_dynamics.decisions import engine as E
    from graph_scale_dynamics.decisions import gates as G
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    known = {s.rule for s in G.STREAMS} | {g.name for g in G.GATES} | set(E.PARKING_RULES)
    assert sorted(rule for rule in known if f"`{rule}`" not in text) == []
    rows = [line.split("|")[2] for line in text.splitlines() if re.match(r"^\| (\d+)? ?\| `", line)]
    named = {rule for cell in rows for rule in re.findall(r"`([a-z_0-9]+)`", cell)}
    assert rows and sorted(named - known) == []
