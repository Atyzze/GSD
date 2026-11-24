from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("zstd") is None,
                                reason="zstd is required to build the native archive")


@pytest.fixture(scope="module")
def release():
    sys.path.insert(0, str(ROOT / "tools"))
    return pytest.importorskip("package_release")


@pytest.fixture(scope="module")
def written(release, tmp_path_factory):
    out = tmp_path_factory.mktemp("release") / "GSD999998.tar.zst"
    return out, release.archive(999998, out)


def test_writing_the_archive_does_not_give_it_the_delivery_name(written, release):
    out, partial = written
    assert partial == release.partial_path(out)
    assert partial.is_file() and partial.stat().st_size > 0
    assert not out.exists(), "the archive had its delivery name before anything verified it"
    assert partial.name.startswith(".") and partial.name.endswith(".partial")


def test_a_failed_verification_leaves_nothing_under_either_name(release, tmp_path, monkeypatch):
    out = tmp_path / "GSD999997.tar.zst"

    def refuse(*_args, **_kwargs):
        raise RuntimeError("verification refused")

    monkeypatch.setattr(release, "verify_archive", refuse)
    with pytest.raises(RuntimeError, match="verification refused"):
        release.package_and_publish(999997, out)
    assert not out.exists(), "an archive that failed verification was published"
    assert not release.partial_path(out).exists(), "the refused archive was left behind"


def test_the_real_verifier_refuses_an_archive_for_another_number(written, release):
    out, partial = written
    with pytest.raises(RuntimeError, match="refusing to publish"):
        release.verify_archive(999998, partial, published_as=out)
    assert not out.exists()


def test_publishing_renames_and_a_stale_partial_is_never_reused(release, tmp_path):
    out = tmp_path / "GSD999996.tar.zst"
    stale = release.partial_path(out)
    stale.write_bytes(b"left by a release killed mid-write")
    partial = release.archive(999996, out)
    assert partial.read_bytes()[:4] == b"\x28\xb5\x2f\xfd", "a fresh zstd frame, not the stale bytes"
    release.publish_archive(partial, out)
    assert out.is_file() and not partial.exists()
