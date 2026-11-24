from __future__ import annotations

import io
import shutil
import subprocess
import tarfile

import pytest

from graph_scale_dynamics.research import bundle_layout as B


def _archive(tmp_path, members, *, zst: bool):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    path = tmp_path / ("bundle.tar.zst" if zst else "bundle.tar")
    if zst:
        path.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=raw.getvalue(), capture_output=True,
                                        check=True).stdout)
    else:
        path.write_bytes(raw.getvalue())
    return path


def _file(name: str, data: bytes):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _link(name: str, to: str):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = tarfile.SYMTYPE, to
    return info, None


@pytest.mark.parametrize("zst", [True, False])
def test_a_member_that_would_land_outside_is_refused(tmp_path, zst):
    if zst and not shutil.which("zstd"):
        pytest.skip("the bundle codec is zstd")
    outside = tmp_path / "outside"
    outside.mkdir()
    archive = _archive(tmp_path, [_link("study/escape", str(outside)), _file("study/escape/planted.txt", b"x")],
                       zst=zst)
    with pytest.raises(tarfile.FilterError):
        B.extract(archive, tmp_path / "into")
    assert not (outside / "planted.txt").exists()
    archive = _archive(tmp_path, [_file("../up.txt", b"x")], zst=zst)
    with pytest.raises(tarfile.FilterError):
        B.extract(archive, tmp_path / "into2")
    assert not (tmp_path / "up.txt").exists()


def test_a_plain_bundle_unpacks_and_a_too_large_one_is_refused(tmp_path):
    if not shutil.which("zstd"):
        pytest.skip("the bundle codec is zstd")
    archive = _archive(tmp_path, [_file("study/study.json", b"{}"), _file("study/a/28.json", b"[1]")], zst=True)
    out = B.extract(archive, tmp_path / "ok")
    assert (out / "study" / "study.json").read_bytes() == b"{}" and (out / "study" / "a" / "28.json").is_file()
    with pytest.raises(ValueError, match="refused"):
        B.extract(archive, tmp_path / "small", max_bytes=2)


def test_no_tool_unpacks_a_bundle_any_other_way():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    offenders = [str(p.relative_to(root)) for p in sorted((root / "tools").glob("*.py"))
                 + sorted((root / "graph_scale_dynamics").rglob("*.py"))
                 if '"--zstd", "-xf"' in p.read_text(encoding="utf-8") or ".extractall(" in p.read_text(encoding="utf-8")]
    assert offenders == ["tools/postgres_instance.py"], offenders
