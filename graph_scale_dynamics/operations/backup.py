from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.connection import connect_database
from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.domain.version import BUILD_NUMBER
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.operations.maintenance import exclusive_maintenance

MANIFEST_VERSION = "gsd-backup-v1"
VAR_STATE = ("study.json", "controls", "salt")
VAR_ROOT = "var_state"


def _var_files(var: Path) -> list[Path]:
    out: list[Path] = []
    for name in VAR_STATE:
        path = Path(var) / name
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out.extend(sorted(p for p in path.rglob("*") if p.is_file() and not p.name.endswith(".partial")))
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


FOLDER_BIN = Path("instance") / "container-runtime" / "postgres-17.10-linux-amd64" / "rootfs" / "usr/lib/postgresql/17/bin"
SYSTEM_BIN_ENV = "GSD_POSTGRES_SYSTEM_BIN"


def _command(name: str, root: Path | None = None) -> str:
    from graph_scale_dynamics import PROJECT_ROOT
    for directory in (os.environ.get(SYSTEM_BIN_ENV), Path(root or PROJECT_ROOT) / FOLDER_BIN):
        if directory and (Path(directory) / name).is_file():
            return str(Path(directory) / name)
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"required PostgreSQL command not found: {name}")
    return path


def _without_password(database: str) -> tuple[str, dict]:
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        params = conninfo_to_dict(database)
    except Exception:
        return database, {}
    password = params.pop("password", None)
    if not password:
        return database, {}
    return make_conninfo(**params), {"PGPASSWORD": str(password)}


def _run(command: list[str], env: dict | None = None) -> None:
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL, env=None if not env else dict(os.environ, **env))


def _safe_member(root: Path, relative: str) -> Path:
    member = Path(relative)
    if member.is_absolute() or not member.parts or ".." in member.parts:
        raise ValueError(f"unsafe backup manifest path: {relative!r}")
    resolved_root = root.resolve()
    resolved = (root / member).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"backup manifest path escapes archive: {relative!r}")
    return resolved


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quiescent(database: str) -> dict:
    conn = connect_database(database)
    try:
        paused = conn.execute("SELECT value FROM control WHERE key='paused'").fetchone()
        jobs = int(conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE status='leased'"
        ).fetchone()["c"])
        analyses = int(conn.execute(
            "SELECT COUNT(*) c FROM analysis_queue WHERE status='leased'"
        ).fetchone()["c"])
        return {
            "paused": bool(paused and paused["value"] == "1"),
            "leased_jobs": jobs,
            "leased_analysis": analyses,
        }
    finally:
        conn.close()


def _verify_blob_set(root: Path, objects: list[dict], *, verify_hashes: bool) -> None:
    store = BlobStore(root)
    expected: set[str] = set()
    for row in objects:
        digest = str(row["digest"])
        if digest in expected:
            raise ValueError(f"duplicate blob in backup manifest: {digest}")
        expected.add(digest)
        stat = store.stat(digest)
        if stat.st_size != int(row["size_bytes"]):
            raise OSError(f"backup blob size mismatch: {digest}")
        if verify_hashes and not store.verify(digest):
            raise OSError(f"backup blob checksum mismatch: {digest}")
    present = set(store.iter_digests())
    if present != expected:
        raise OSError(
            f"backup blob manifest mismatch: missing={len(expected-present)} "
            f"extra={len(present-expected)}"
        )


def _create_backup_locked(database: str, blobs_root: Path, output: Path, *, allow_live: bool = False,
                          var: Path | None = None) -> dict:
    state = _quiescent(database)
    if not allow_live and (not state["paused"] or state["leased_jobs"] or state["leased_analysis"]):
        raise RuntimeError(
            "refusing non-quiescent backup: pause the fleet and wait for all leases to drain "
            f"(state={state})"
        )
    if output.exists():
        raise FileExistsError(f"backup destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        dump = temp / "database.dump"
        target, secret = _without_password(database)
        _run([
            _command("pg_dump"), "--format=custom", "--no-owner", "--no-privileges",
            "--file", str(dump), target,
        ], *([secret] if secret else []))
        _fsync_file(dump)

        source_store = BlobStore(blobs_root)
        destination_root = temp / "blob_store"
        destination_store = BlobStore(destination_root)
        durable_digests = set(source_store.iter_digests())
        transient_digests = set(source_store.iter_transient_digests() or ())
        digests = sorted(durable_digests | transient_digests)
        blob_records: list[dict] = []
        transient_materialized = 0
        for digest in digests:
            source_path = source_store._resolved_path(digest)
            if digest in transient_digests and digest not in durable_digests:
                transient_materialized += 1
            actual = _sha256(source_path)
            if actual != digest:
                raise OSError(f"source blob failed digest verification: {digest}")
            destination = destination_store._path(digest)
            destination_store._ensure_durable_dir(destination.parent)
            shutil.copy2(source_path, destination)
            if _sha256(destination) != digest:
                raise OSError(f"copied blob failed digest verification: {digest}")
            blob_records.append({"digest": digest, "size_bytes": source_path.stat().st_size})
        shutil.rmtree(destination_root / "staging", ignore_errors=True)
        (destination_root / "staging").mkdir()
        state_records = []
        for source in _var_files(var) if var is not None else []:
            relative = source.relative_to(var)
            destination = temp / VAR_ROOT / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            state_records.append({"path": relative.as_posix(), "sha256": _sha256(destination),
                                  "size_bytes": destination.stat().st_size})

        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "build": BUILD_NUMBER,
            "created_utc": utc_now(),
            "quiescence": state,
            "database": {
                "file": dump.name,
                "sha256": _sha256(dump),
                "size_bytes": dump.stat().st_size,
            },
            "blobs": {
                "root": "blob_store",
                "count": len(blob_records),
                "size_bytes": sum(row["size_bytes"] for row in blob_records),
                "objects": blob_records,
                "transient_materialized_count": int(transient_materialized),
            },
            "var_state": {"root": VAR_ROOT, "files": state_records},
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _fsync_file(manifest_path)
        _fsync_dir(temp)
        os.replace(temp, output)
        _fsync_dir(output.parent)
        return manifest
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def create_backup(database: str, blobs_root: Path, output: Path, *, allow_live: bool = False,
                  var: Path | None = None) -> dict:
    with Repo(database) as repo:
        with exclusive_maintenance(repo):
            return _create_backup_locked(database, blobs_root, output, allow_live=allow_live, var=var)


def verify_backup(backup: Path, *, verify_blobs: bool = True) -> dict:
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError("unsupported backup manifest version")
    dump = _safe_member(backup, str(manifest["database"]["file"]))
    if dump.stat().st_size != int(manifest["database"]["size_bytes"]):
        raise OSError("database dump size mismatch")
    if _sha256(dump) != manifest["database"]["sha256"]:
        raise OSError("database dump checksum mismatch")

    objects = manifest["blobs"]["objects"]
    if int(manifest["blobs"]["count"]) != len(objects):
        raise OSError("backup blob count does not match manifest object list")
    object_size = sum(int(row["size_bytes"]) for row in objects)
    if int(manifest["blobs"]["size_bytes"]) != object_size:
        raise OSError("backup blob byte total does not match manifest object list")
    blob_root = _safe_member(backup, str(manifest["blobs"]["root"]))
    _verify_blob_set(blob_root, objects, verify_hashes=verify_blobs)
    state = manifest.get("var_state") or {}
    for row in state.get("files") or []:
        member = _safe_member(backup, f"{state['root']}/{row['path']}")
        if member.stat().st_size != int(row["size_bytes"]) or _sha256(member) != row["sha256"]:
            raise OSError(f"backup state file mismatch: {row['path']}")
    return manifest | {"verified_utc": utc_now(), "verified_blobs": bool(verify_blobs)}


def restore_var_state(backup: Path, manifest: dict, var: Path, *, force: bool = False) -> list[str]:
    state = manifest.get("var_state") or {}
    rows = state.get("files") or []
    targets = [_safe_member(Path(var), str(row["path"])) for row in rows]
    present = [row["path"] for row, target in zip(rows, targets, strict=True) if target.exists()]
    if present and not force:
        raise FileExistsError(f"the state directory already holds {present[:3]}; pass --force to replace them")
    for row, target in zip(rows, targets, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_safe_member(backup, f"{state['root']}/{row['path']}"), target)
    return [row["path"] for row in rows]


def _restore_backup_locked(backup: Path, database: str, blobs_root: Path, *, force: bool = False) -> dict:
    manifest = verify_backup(backup, verify_blobs=True)
    if blobs_root.exists() and any(blobs_root.iterdir()) and not force:
        raise FileExistsError("target blob root is not empty; pass --force only for a disposable restore")

    temp_blob_root = blobs_root.with_name(f".{blobs_root.name}.restore-{os.getpid()}")
    shutil.rmtree(temp_blob_root, ignore_errors=True)
    source_blob_root = _safe_member(backup, str(manifest["blobs"]["root"]))
    shutil.copytree(source_blob_root, temp_blob_root)
    old_blob_root = blobs_root.with_name(f".{blobs_root.name}.previous-{os.getpid()}")
    shutil.rmtree(old_blob_root, ignore_errors=True)
    had_target = blobs_root.exists()
    swapped = False
    try:
        _verify_blob_set(temp_blob_root, manifest["blobs"]["objects"], verify_hashes=True)

        if had_target:
            os.replace(blobs_root, old_blob_root)
        try:
            os.replace(temp_blob_root, blobs_root)
            _fsync_dir(blobs_root.parent)
            swapped = True
        except Exception:
            if had_target and old_blob_root.exists() and not blobs_root.exists():
                os.replace(old_blob_root, blobs_root)
                _fsync_dir(blobs_root.parent)
            raise

        dump = _safe_member(backup, str(manifest["database"]["file"]))
        target, secret = _without_password(database)
        command = [
            _command("pg_restore"), "--single-transaction", "--exit-on-error",
            "--no-owner", "--no-privileges", "--dbname", target,
        ]
        if force:
            command[1:1] = ["--clean", "--if-exists"]
        command.append(str(dump))
        try:
            _run(command, *([secret] if secret else []))
        except Exception:
            if swapped:
                failed_blob_root = blobs_root.with_name(
                    f".{blobs_root.name}.failed-{os.getpid()}"
                )
                shutil.rmtree(failed_blob_root, ignore_errors=True)
                if blobs_root.exists():
                    os.replace(blobs_root, failed_blob_root)
                if had_target and old_blob_root.exists():
                    os.replace(old_blob_root, blobs_root)
                else:
                    shutil.rmtree(blobs_root, ignore_errors=True)
                _fsync_dir(blobs_root.parent)
                shutil.rmtree(failed_blob_root, ignore_errors=True)
            raise

        shutil.rmtree(old_blob_root, ignore_errors=True)
        return manifest
    except Exception:
        shutil.rmtree(temp_blob_root, ignore_errors=True)
        raise


def restore_backup(backup: Path, database: str, blobs_root: Path, *, force: bool = False) -> dict:
    with Repo(database) as repo:
        with exclusive_maintenance(repo):
            return _restore_backup_locked(backup, database, blobs_root, force=force)
