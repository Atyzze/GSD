from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _cmdclass():
    pytest.importorskip("setuptools", reason="setup.py needs setuptools to import")
    spec = importlib.util.spec_from_file_location("gsd_setup_shim", ROOT / "setup.py")
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["setup.py", "--version"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    if not module.CMDCLASS:
        pytest.skip("no wheel machinery available in this environment")
    return module.CMDCLASS


def _command():
    command = _cmdclass()["bdist_wheel"]
    from setuptools import Distribution

    distribution = Distribution({"name": "gsd", "version": "0"})
    instance = command(distribution)
    instance.finalize_options()
    return instance


def test_the_project_declares_a_bdist_wheel_override():
    assert "bdist_wheel" in _cmdclass(), (
        "no bdist_wheel override: the wheel would be tagged py3-none-any and would "
        "install on platforms whose bootstrap runtime it does not carry"
    )


def test_the_archive_root_stays_purelib():
    assert _command().root_is_pure is True


def test_the_wheel_is_tagged_py3_none_for_this_platform():
    command = _command()
    assert command.plat_name_supplied is True, (
        "the platform was not supplied, so the tag would fall back to `any`"
    )
    python_tag, abi_tag, platform_tag = command.get_tag()
    assert (python_tag, abi_tag) == ("py3", "none")
    assert platform_tag != "any", (
        "the wheel claims to run anywhere while carrying a Linux x86-64 runtime"
    )
    assert "_".join((python_tag, abi_tag, platform_tag)).startswith("py3_none_")


def test_the_release_tool_still_requires_that_tag():
    source = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert "-py3-none-linux_x86_64.whl" in source


def test_setup_py_ships_in_the_release_archive():
    source = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    root_files = source[source.index("ROOT_FILES = {"):source.index("}", source.index("ROOT_FILES = {"))]
    assert '"setup.py"' in root_files
