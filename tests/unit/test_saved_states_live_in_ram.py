from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.resume_state import resume_path, resume_root
from graph_scale_dynamics.services.worker.main import publication_roots


def _under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def test_the_child_is_told_to_keep_its_state_on_the_volatile_root(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    roots = publication_roots(blobs)
    assert Path(roots["resume_root"]) == blobs.volatile_root
    assert Path(roots["publish_blob_root"]) == blobs.root, "artifacts still publish durably"
    state = resume_path(roots["resume_root"], "a" * 64)
    assert not _under(state, blobs.root), f"the saved state would be written under the disk root: {state}"
    assert _under(state, blobs.volatile_root)


def test_every_reader_finds_the_states_where_the_child_keeps_them(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    assert resume_root(blobs.root) == blobs.volatile_root
