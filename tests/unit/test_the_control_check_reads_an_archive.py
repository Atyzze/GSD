from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("positive_control_tool", ROOT / "tools" / "positive_control.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _study(folder: Path) -> Path:
    study = folder / "study_252_x"
    study.mkdir(parents=True)
    (study / "study.json").write_text(json.dumps({"campaigns": [
        {"campaign_id": "6", "name": "campaign-standing-controls", "bundle": "campaign_6_part"}]}))
    (study / "campaign_6_part").mkdir()
    return study


def test_the_check_reads_an_archive(tmp_path):
    tool = _tool()
    study = _study(tmp_path / "src")
    archive = tmp_path / "study.tar.zst"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        tar.add(study, arcname=study.name)
    archive.write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
    folder = tool._as_folder(archive)
    assert (folder / "study_252_x" / "study.json").is_file()
    assert tool._as_folder(folder) == folder
