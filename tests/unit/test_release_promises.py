from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOL = ROOT / "tools" / "package_release.py"

ENTRY_DOCS = ("README.md",)


def _release_module():
    spec = importlib.util.spec_from_file_location("gsd_package_release_under_test", RELEASE_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_promised_root_file_exists():
    module = _release_module()
    missing = sorted(name for name in module.REQUIRED_ROOT_FILES if not (ROOT / name).is_file())
    assert not missing, (
        "package_release.REQUIRED_ROOT_FILES promises files that are not in the tree: "
        + ", ".join(missing)
        + ". The packaging walk skips a missing root file silently, so the archive "
        "ships without it and nothing fails. Write the file, or move it to "
        "OPTIONAL_ROOT_FILES with the reason."
    )


def test_the_optional_list_is_a_subset_of_what_is_promised():
    module = _release_module()
    stray = sorted(module.OPTIONAL_ROOT_FILES - module.ROOT_FILES)
    assert not stray, (
        "OPTIONAL_ROOT_FILES names files ROOT_FILES does not list, so the packaging "
        "walk never looks for them: " + ", ".join(stray)
    )


def test_every_promised_root_dir_exists():
    module = _release_module()
    exempt = {"attic", "graph_scale_dynamics.services"}
    missing = sorted(name for name in module.ROOT_DIRS
                     if name not in exempt and not (ROOT / name).is_dir())
    assert not missing, (
        "package_release.ROOT_DIRS names directories that are not in the tree: "
        + ", ".join(missing)
    )


def test_the_environment_script_is_findable_from_an_entry_document():
    script = ROOT / "tools" / "prepare_environment.sh"
    assert script.is_file(), "the bring-up script is gone; this test is now the wrong test"

    found = [name for name in ENTRY_DOCS
             if (ROOT / name).is_file()
             and "prepare_environment.sh" in (ROOT / name).read_text(encoding="utf-8")]
    assert found, (
        "no entry document points at tools/prepare_environment.sh. Checked: "
        + ", ".join(ENTRY_DOCS)
        + ". Without it, the PostgreSQL lanes appear unrunnable and the skip "
        "message blames the wrong thing."
    )


def test_the_bring_up_script_ships():
    module = _release_module()
    assert "tools" in module.ROOT_DIRS, "tools/ is not in the release archive"
    assert "tools/prepare_environment.sh" in module.REQUIRED_RELEASE_PATHS
    script = ROOT / "tools" / "prepare_environment.sh"
    assert script.stat().st_mode & 0o111, (
        "tools/prepare_environment.sh is not executable; an archive that ships it "
        "unexecutable ships a script the reader has to know to chmod"
    )


@pytest.mark.parametrize("name", ENTRY_DOCS)
def test_entry_documents_exist(name):
    assert (ROOT / name).is_file(), (
        f"{name} is named as an entry point by the other tests in this file and "
        "is not in the tree"
    )
