from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "graph_scale_dynamics"
RAW = {"metrics_json", "summary_json"}
RAW_550 = {"spec_json", "facts_json"}

MAY_NAME = {
    "db/repo_campaigns.py": "the repository's own queries and writers, on database rows",
    "db/repo_candidates.py": "the repository's own queries and writers, on database rows",
    "db/repo_records.py": "the repository's own queries and writers, on database rows",
    "operations/campaign_archive.py": "the archive copies database rows",
    "research/anchors.py": "anchors read rung summaries from the database",
    "services/api/landscape_worker.py": "the landscape reads database rows",
    "services/api/main.py": "the API's pages read database rows",
    "services/api/overview.py": "the API's pages read database rows",
    "reporting/reset_rules_report.py": "reads `metrics` and names the text only for a row that has no `metrics`",
    "research/report_pipeline.py": "the collector names the columns it parses (checked below)",
    "reporting/study_tables.py": "the study's tables read rung summaries from the database a page at a time",
    "operations/outliers.py": "the outliers' queue reads rung summaries from the database",
    "services/api/law_elsewhere.py": "the law page reads the rung summaries of the law's other campaigns from the database",
}


def _named(path: Path) -> list[ast.Constant]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value in RAW]


def test_only_the_listed_modules_name_the_raw_columns():
    naming = {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")
              if "__pycache__" not in path.parts and _named(path)}
    assert naming <= set(MAY_NAME), (
        "these name a raw JSON column the snapshot's rows no longer carry; if they read a snapshot row they read "
        f"nothing: {sorted(naming - set(MAY_NAME))}")
    assert set(MAY_NAME) <= naming, f"no longer named, so no longer listed: {sorted(set(MAY_NAME) - naming)}"


def test_the_collector_names_them_only_to_parse_them():
    tree = ast.parse((PACKAGE / "research/report_pipeline.py").read_text(encoding="utf-8"))
    parsed = {id(arg) for node in ast.walk(tree) if isinstance(node, ast.Call)
              and getattr(node.func, "id", None) == "parsed_rows" for arg in node.args}
    stray = [node.lineno for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and node.value in RAW | RAW_550 and id(node) not in parsed]
    assert not stray, f"report_pipeline.py names a raw column outside `parsed_rows` at lines {stray}"


MAY_NAME_UNREAD_SECTIONS = {
    "scaleflow/one_shot.py": "a job's one shot writes them into its metrics",
    "research/what_happened.py": "a law's story, read from database rows (`services/api/readings_route.py`)",
    "observability/two_chains.py": "both chains of a law, read from database rows (`services/api/readings_route.py`)",
    "services/analyzer/child.py": "the analysis writes the chains' courses into a seed's metrics",
    "research/snapshot_rows.py": "names them to let them go",
}


def test_only_the_listed_modules_name_the_sections_the_snapshot_lets_go():
    from graph_scale_dynamics.research.snapshot_rows import UNREAD_METRICS_SECTIONS
    naming = set()
    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Constant) and node.value in UNREAD_METRICS_SECTIONS for node in ast.walk(tree)):
            naming.add(path.relative_to(PACKAGE).as_posix())
    assert naming <= set(MAY_NAME_UNREAD_SECTIONS), (
        "these name a section of a measurement's metrics the report snapshot lets go; if a report reads it from a "
        f"snapshot row it reads nothing: {sorted(naming - set(MAY_NAME_UNREAD_SECTIONS))}")
    assert set(MAY_NAME_UNREAD_SECTIONS) <= naming, (
        f"no longer named, so no longer listed: {sorted(set(MAY_NAME_UNREAD_SECTIONS) - naming)}")
