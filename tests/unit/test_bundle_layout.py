from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.research.bundle_layout import read_report, report_path


def test_reads_dashboard_flat_layout(tmp_path):
    (tmp_path / "05-phenotypes.json").write_text(json.dumps({"body": {"specimens": [1]}}))
    assert read_report(tmp_path, "05")["body"]["specimens"] == [1]
    assert read_report(tmp_path, "05-phenotypes.json")["body"]["specimens"] == [1]


def test_reads_report_export_nested_layout(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "05.json").write_text(json.dumps({"body": {"specimens": [2]}}))
    assert read_report(tmp_path, "05-phenotypes.json")["body"]["specimens"] == [2]
    assert report_path(tmp_path, "5").name == "05.json"


def test_missing_report_names_both_layouts(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        read_report(tmp_path, "23")
    assert "23-<slug>.json" in str(exc.value) and "reports/23.json" in str(exc.value)
