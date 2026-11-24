from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "runtime" / "bootstrap" / "linux-amd64"


def _instance_module():
    spec = importlib.util.spec_from_file_location("gsd_pg_instance_names", ROOT / "tools" / "postgres_instance.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not sys.platform.startswith("linux") or not Path("/bin/sleep").is_file(),
                    reason="needs Linux /proc and an ELF to run")
def test_a_wrapped_postgres_binary_runs_under_its_own_name(tmp_path, monkeypatch):
    pg = _instance_module()
    runtime = tmp_path / "runtime"
    rootfs = runtime / "rootfs"
    libdir = rootfs / "lib" / "x86_64-linux-gnu"
    libdir.mkdir(parents=True)
    shutil.copy2(BUNDLED / "ld-linux-x86-64.so.2", libdir / "ld-linux-x86-64.so.2")
    shutil.copy2(BUNDLED / "libc.so.6", libdir / "libc.so.6")
    bindir = rootfs / "usr" / "lib" / "postgresql" / "17" / "bin"
    bindir.mkdir(parents=True)
    shutil.copy2("/bin/sleep", bindir / "postgres")
    monkeypatch.setattr(pg, "OCI_ROOT", runtime)
    monkeypatch.setattr(pg, "OCI_ROOTFS", rootfs)

    pg._wrap_postgres_binaries()
    pg._wrap_postgres_binaries()

    assert (bindir / "postgres.gsd-real").is_file()
    link = runtime / "named-loaders" / "gsd-postgres"
    assert link.is_symlink() and link.resolve() == (libdir / "ld-linux-x86-64.so.2").resolve()

    proc = subprocess.Popen([str(bindir / "postgres"), "5"])
    try:
        deadline = time.monotonic() + 5.0
        name = ""
        while time.monotonic() < deadline:
            name = Path(f"/proc/{proc.pid}/comm").read_text().strip()
            if name == "gsd-postgres" or name == "ld-linux-x86-64":
                break
            time.sleep(0.02)
        assert name == "gsd-postgres", (
            f"btop would show {name!r}; a database process must be recognisable by name")
    finally:
        proc.kill()
        proc.wait(timeout=5)
