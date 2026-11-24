from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration.cells import plan_extension_cells, suite_families

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "calibration" / "seed_table.json"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("collect_calibration", ROOT / "tools" / "collect_calibration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_the_extension(document: dict) -> dict:
    for task in plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS):
        document["cells"][task["key"]] = {
            "family": task["family"], "parameter": task["parameter"], "seed": task["seed"], "n": task["n"],
            "status": "ok", "cell_fingerprint": FP.cell_fingerprint(task["family"], str(ROOT)),
            "channels": {}, "peak_rss_bytes": 3 * task["n"] * 1024}
    return document


def _without_the_extension(document: dict) -> dict:
    planned = {task["key"] for task in plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)}
    document["cells"] = {key: cell for key, cell in document["cells"].items() if key not in planned}
    return document


def test_the_collection_says_what_is_current_and_what_each_family_needed(tool, tmp_path):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    table = tmp_path / "probe_calibration.json"
    table.write_text(json.dumps(_without_the_extension(json.loads(SEED.read_text()))))
    packed = tool.collect(ROOT, tmp_path, table_path=table)
    with zipfile.ZipFile(packed) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert json.loads(bundle.read("probe_calibration.json"))["cells"] == json.loads(table.read_text())["cells"]
    assert manifest["gate_complete"] and not manifest["extension_complete"]
    assert manifest["extension"]["missing"] == len(plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS))


def test_a_partial_table_becomes_a_seed_only_when_asked(tool, tmp_path):
    table = tmp_path / "probe_calibration.json"
    table.write_text(json.dumps(_without_the_extension(json.loads(SEED.read_text()))))
    packed = tool.collect(ROOT, tmp_path, table_path=table)
    with pytest.raises(SystemExit, match="partial"):
        tool.install_seed(packed, ROOT, target=tmp_path / "seed_table.json")
    target, summary = tool.install_seed(packed, ROOT, partial=True, target=tmp_path / "seed_table.json")
    assert json.loads(target.read_text())["origin"]["seeded_from"]["source"] == packed.name
    assert not summary["extension_complete"]


def test_the_shipped_seed_is_the_operators_finished_table():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import owed
    from graph_scale_dynamics.calibration.cells import plan_cells
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    seed = json.loads(SEED.read_text())
    ladders = plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)
    extension = plan_extension_cells(suite_families(), seeds=C.EXTENSION_SEEDS)
    assert len(seed["cells"]) == len(ladders) + len(extension), "every ladder at ten seeds, and the cells past them"
    assert all(task["key"] in seed["cells"] for task in ladders + extension)
    seeded = (seed.get("origin") or {}).get("seeded_from", {})
    assert seeded["source"].startswith("calibration_") and seeded["source"].endswith(".zip"), (
        "the one file the calibration's command ends on, by the name the host gave it")
    assert seeded["reading"]["gate"] == {"current": len(ladders), "failed": 0, "missing": 0, "stale": 0}
    assert seeded["reading"]["extension"] == {"current": len(extension), "failed": 0, "missing": 0, "stale": 0}
    assert seed["authoritative"] is True and seed["profile"]["name"] == "full", "a seed, not a reduced table"
    assert seed["analysis_version"] == ANALYSIS_VERSION and seed["suite_version"] == C.SUITE_VERSION
    assert seed["deviation"]["verdict"] == "PASS" and not seed["deviation"]["failing_families"]
    assert owed.recalibration_owed() is None, "measured under this tree's probes: nothing of it is owed"
    assert all(cell.get("d_s_margins") for cell in seed["cells"].values()), "a fresh folder owes no margins either"
    assert all(isinstance(cell.get("peak_rss_bytes"), int) and cell["status"] == "ok" for cell in seed["cells"].values())
    assert {run["host"] for run in seed["runs"]} == {seed["origin"]["computed_on"]}, "one host measured all of it"


def test_a_finished_table_becomes_the_seed_and_never_the_live_table(tool, tmp_path):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    table = tmp_path / "probe_calibration.json"
    table.write_text(json.dumps(_with_the_extension(json.loads(SEED.read_text()))))
    packed = tool.collect(ROOT, tmp_path, table_path=table)
    target, summary = tool.install_seed(packed, ROOT, target=tmp_path / "seed_table.json")
    assert summary["gate_complete"] and summary["extension_complete"]
    seeded = json.loads(target.read_text())
    assert seeded["contract"] == C.CONTRACT and len(seeded["cells"]) > 1550
    with pytest.raises(SystemExit, match="never probe_calibration.json"):
        tool.install_seed(packed, ROOT, target=tmp_path / C.DURABLE_NAME)


def test_a_report_bundle_carries_the_table_back_to_the_seed(tool, tmp_path):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    import io
    import shutil
    import subprocess
    import tarfile

    from graph_scale_dynamics.reporting.evidence import EVIDENCE_ITEMS
    assert ("probe_calibration", "/api/calibration/table", "json") in EVIDENCE_ITEMS
    if not shutil.which("zstd"):
        pytest.skip("the zstd executable is not installed here")
    document = _with_the_extension(json.loads(SEED.read_text()))
    payload = json.dumps(document, indent=1, sort_keys=True).encode("utf-8")
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w") as archive:
        member = tarfile.TarInfo("campaign_1_reports_2026-09-26T09-20-02Z_4a1ea8fc/evidence/probe_calibration.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    bundle = tmp_path / "campaign_1_reports_2026-09-26T09-20-02Z_4a1ea8fc.tar.zst"
    bundle.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=packed.getvalue(), capture_output=True,
                                      check=True).stdout)
    target, summary = tool.install_seed(bundle, ROOT, target=tmp_path / "seed_table.json")
    assert json.loads(target.read_text())["cells"] == document["cells"]
    assert summary["gate_complete"] and summary["extension_complete"]
    assert json.loads(target.read_text())["origin"]["seeded_from"]["source"] == bundle.name
    empty = tmp_path / "campaign_1_reports_old.tar.zst"
    quiet = io.BytesIO()
    with tarfile.open(fileobj=quiet, mode="w") as archive:
        member = tarfile.TarInfo("campaign_1_reports_old/manifest.json")
        member.size = 2
        archive.addfile(member, io.BytesIO(b"{}"))
    empty.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=quiet.getvalue(), capture_output=True,
                                     check=True).stdout)
    with pytest.raises(SystemExit, match="carries no evidence/probe_calibration.json"):
        tool.install_seed(empty, ROOT, target=tmp_path / "seed_table.json")
