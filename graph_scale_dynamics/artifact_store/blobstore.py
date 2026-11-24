from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import re
import tempfile
from pathlib import Path

from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir

_HEX64 = re.compile(r"[0-9a-fA-F]{64}")


class BlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        (self.root / "staging").mkdir(parents=True, exist_ok=True)
        allow_persistent = os.environ.get("GSD_ALLOW_PERSISTENT_SCRATCH", "").strip().lower() in {"1", "true", "yes", "on"}
        chosen = choose_volatile_dir(
            namespace=f"blobstore:{self.root.resolve()}",
            allow_persistent_fallback=allow_persistent or os.name != "posix",
        )
        volatile_path = chosen.get("path")
        if volatile_path and chosen.get("volatile"):
            self.volatile_root = Path(str(volatile_path))
        elif volatile_path and allow_persistent:
            self.volatile_root = Path(str(volatile_path))
        else:
            raise RuntimeError(
                "RAM-backed scratch unavailable; refusing persistent intermediate writes "
                "(set GSD_VOLATILE_DIR to tmpfs or GSD_ALLOW_PERSISTENT_SCRATCH=1 to override)"
            )
        self.staging_root = self.volatile_root / "staging"
        self.transient_root = self.volatile_root / "transient-blobs"
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.transient_root.mkdir(parents=True, exist_ok=True)
        self.staging_backend = chosen | {"path": str(self.staging_root)}

    @classmethod
    def reader(cls, root: str | Path) -> "BlobStore":
        store = cls.__new__(cls)
        store.root = Path(root)
        store.volatile_root = store.staging_root = None
        store.transient_root = store.root / "no-transient-tier"
        store.staging_backend = {"path": None, "volatile": False, "reader": True}
        return store

    @staticmethod
    def _validate_digest(digest: str) -> str:
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise ValueError("artifact digest must be 64 hexadecimal characters")
        return digest.lower()

    def _path(self, digest: str) -> Path:
        digest = self._validate_digest(digest)
        return self.root / "blobs" / digest[:2] / digest[2:4] / digest

    def _transient_path(self, digest: str) -> Path:
        digest = self._validate_digest(digest)
        return self.transient_root / digest[:2] / digest[2:4] / digest

    def _resolved_path(self, digest: str) -> Path:
        digest = self._validate_digest(digest)
        durable = self._path(digest)
        if durable.exists():
            return durable
        transient = self._transient_path(digest)
        if transient.exists():
            return transient
        return durable

    def _ensure_durable_dir(self, path: Path) -> None:
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        path.mkdir(parents=True, exist_ok=True)
        for created in reversed(missing):
            self._fsync_dir(created)
            self._fsync_dir(created.parent)

    def staging_dir(self, attempt_id: str) -> Path:
        path = self.staging_root / attempt_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def commit_file(self, source: Path) -> tuple[str, int]:
        hex_digest, size = self._hash_file(source)
        target = self._path(hex_digest)
        self._ensure_durable_dir(target.parent)
        if target.exists():
            existing_digest, existing_size = self._hash_file(target)
            if existing_digest != hex_digest or existing_size != size:
                raise OSError(f"existing blob {hex_digest} failed content verification")
            source.unlink(missing_ok=True)
            return hex_digest, size
        try:
            same_device = source.stat().st_dev == target.parent.stat().st_dev
        except OSError:
            same_device = False
        if same_device:
            with source.open("rb+") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(source, target)
        else:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{hex_digest}.", suffix=".tmp", dir=target.parent)
            durable_tmp = Path(tmp_name)
            try:
                with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                    dst.flush()
                    os.fsync(dst.fileno())
                os.replace(durable_tmp, target)
                source.unlink(missing_ok=True)
            finally:
                durable_tmp.unlink(missing_ok=True)
        self._fsync_dir(target.parent)
        return hex_digest, size

    def put_json_stream_with_stats(self, payload, *, compresslevel: int = 1) -> tuple[str, int, int]:
        level = max(1, min(9, int(compresslevel)))
        staging = self.staging_root
        staging.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".gsd-json-", suffix=".json.gz", dir=staging)
        os.close(fd)
        temporary = Path(tmp_name)
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
        logical_bytes = 0
        try:
            with temporary.open("wb") as raw_out:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out,
                                   compresslevel=level, mtime=0) as zipped:
                    for chunk in encoder.iterencode(payload):
                        encoded = chunk.encode("utf-8")
                        logical_bytes += len(encoded)
                        zipped.write(encoded)
                raw_out.flush()
                os.fsync(raw_out.fileno())
            digest, stored_bytes = self.commit_file(temporary)
            return digest, stored_bytes, logical_bytes
        finally:
            temporary.unlink(missing_ok=True)


    def _commit_transient_file(self, source: Path) -> tuple[str, int]:
        hex_digest, size = self._hash_file(source)
        target = self._transient_path(hex_digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing_digest, existing_size = self._hash_file(target)
            if existing_digest != hex_digest or existing_size != size:
                raise OSError(f"existing transient blob {hex_digest} failed content verification")
            source.unlink(missing_ok=True)
            return hex_digest, size
        try:
            os.replace(source, target)
        except OSError:
            shutil.copyfile(source, target)
            source.unlink(missing_ok=True)
        return hex_digest, size

    def put_json_stream_transient_with_stats(self, payload, *, compresslevel: int = 1) -> tuple[str, int, int]:
        level = max(1, min(9, int(compresslevel)))
        staging = self.staging_root
        staging.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".gsd-json-transient-", suffix=".json.gz", dir=staging)
        os.close(fd)
        temporary = Path(tmp_name)
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
        logical_bytes = 0
        try:
            with temporary.open("wb") as raw_out:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out,
                                   compresslevel=level, mtime=0) as zipped:
                    for chunk in encoder.iterencode(payload):
                        encoded = chunk.encode("utf-8")
                        logical_bytes += len(encoded)
                        zipped.write(encoded)
                raw_out.flush()
            digest, stored_bytes = self._commit_transient_file(temporary)
            return digest, stored_bytes, logical_bytes
        finally:
            temporary.unlink(missing_ok=True)

    def put_json_stream_transient(self, payload, *, compresslevel: int = 1) -> tuple[str, int]:
        digest, stored_bytes, _logical_bytes = self.put_json_stream_transient_with_stats(
            payload, compresslevel=compresslevel
        )
        return digest, stored_bytes

    def put_json_stream(self, payload, *, compresslevel: int = 1) -> tuple[str, int]:
        digest, stored_bytes, _logical_bytes = self.put_json_stream_with_stats(
            payload, compresslevel=compresslevel
        )
        return digest, stored_bytes

    def put_json(self, payload, *, gz: bool = True, compresslevel: int = 6) -> tuple[str, int]:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
        blob = gzip.compress(raw, compresslevel=max(1, min(9, int(compresslevel))), mtime=0) if gz else raw
        return self.put_bytes(blob)

    def put_bytes(self, blob: bytes) -> tuple[str, int]:
        digest = hashlib.sha256(blob).hexdigest()
        target = self._path(digest)
        self._ensure_durable_dir(target.parent)
        if target.exists():
            existing_digest, existing_size = self._hash_file(target)
            if existing_digest != digest or existing_size != len(blob):
                raise OSError(f"existing blob {digest} failed content verification")
            return digest, len(blob)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp_name, target)
                os.unlink(tmp_name)
            except FileExistsError as exc:
                os.unlink(tmp_name)
                existing_digest, existing_size = self._hash_file(target)
                if existing_digest != digest or existing_size != len(blob):
                    raise OSError(
                        f"concurrent blob {digest} failed content verification") from exc
            self._fsync_dir(target.parent)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
        return digest, len(blob)

    def get_bytes(self, digest: str, *, verify: bool = True,
                  max_bytes: int | None = None) -> bytes:
        digest = self._validate_digest(digest)
        path = self._resolved_path(digest)
        if max_bytes is not None and path.stat().st_size > max_bytes:
            raise ValueError(f"artifact exceeds compressed size limit of {max_bytes} bytes")
        blob = path.read_bytes()
        if verify and hashlib.sha256(blob).hexdigest() != digest:
            raise OSError(f"artifact digest verification failed for {digest}")
        return blob

    def get_json(self, digest: str, *, verify: bool = True,
                 max_compressed_bytes: int | None = None,
                 max_decoded_bytes: int | None = None):
        blob = self.get_bytes(digest, verify=verify, max_bytes=max_compressed_bytes)
        if blob[:2] == b"\x1f\x8b":
            if max_decoded_bytes is None:
                blob = gzip.decompress(blob)
            else:
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(blob)) as handle:
                    decoded = handle.read(max_decoded_bytes + 1)
                if len(decoded) > max_decoded_bytes:
                    raise ValueError(
                        f"artifact exceeds decoded size limit of {max_decoded_bytes} bytes"
                    )
                blob = decoded
        elif max_decoded_bytes is not None and len(blob) > max_decoded_bytes:
            raise ValueError(f"artifact exceeds decoded size limit of {max_decoded_bytes} bytes")
        return json.loads(blob.decode("utf-8"))

    def exists(self, digest: str) -> bool:
        try:
            return self._resolved_path(self._validate_digest(digest)).is_file()
        except (OSError, ValueError):
            return False

    def stat(self, digest: str) -> os.stat_result:
        return self._resolved_path(self._validate_digest(digest)).stat()

    def stale_temporaries(self, older_than_seconds: float = 3600.0) -> list[Path]:
        import time
        root = self.root / "blobs"
        if not root.exists():
            return []
        cutoff = time.time() - float(older_than_seconds)
        found = []
        for path in root.glob("*/*/.*"):
            if path.suffix in (".tmp", ".spill") and path.is_file():
                try:
                    if path.stat().st_mtime < cutoff:
                        found.append(path)
                except OSError:
                    continue
        return sorted(found)

    def iter_digests(self):
        root = self.root / "blobs"
        if not root.exists():
            return
        for path in root.glob("*/*/*"):
            if path.is_file():
                try:
                    yield self._validate_digest(path.name)
                except ValueError:
                    continue

    def verify(self, digest: str) -> bool:
        try:
            digest = self._validate_digest(digest)
            path = self._resolved_path(digest)
            if not path.exists():
                return False
            return self._hash_file(path)[0] == digest
        except (OSError, ValueError):
            return False

    def verify_durable(self, digest: str) -> bool:
        try:
            digest = self._validate_digest(digest)
            path = self._path(digest)
            return path.exists() and self._hash_file(path)[0] == digest
        except (OSError, ValueError):
            return False

    def iter_transient_digests(self):
        root = self.transient_root
        if not root.exists():
            return
        for path in root.glob("*/*/*"):
            if path.is_file():
                try:
                    yield self._validate_digest(path.name)
                except ValueError:
                    continue

    def delete_transient(self, digest: str) -> bool:
        path = self._transient_path(self._validate_digest(digest))
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        for directory in (path.parent, path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break
        return True

    def delete(self, digest: str) -> bool:
        path = self._path(self._validate_digest(digest))
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        self._fsync_dir(path.parent)
        for directory in (path.parent, path.parent.parent):
            try:
                directory.rmdir()
                self._fsync_dir(directory.parent)
            except OSError:
                break
        return True

    def spill_transient(self, digest: str) -> int:
        digest = self._validate_digest(digest)
        source, target = self._transient_path(digest), self._path(digest)
        try:
            size = source.stat().st_size
        except FileNotFoundError:
            return 0
        if target.exists() and self.verify_durable(digest):
            return int(size)
        self._ensure_durable_dir(target.parent)
        temporary = target.with_name(f".{digest}.{os.getpid()}.spill")
        hasher = hashlib.sha256()
        try:
            with source.open("rb") as reader, temporary.open("wb") as writer:
                for chunk in iter(lambda: reader.read(1 << 20), b""):
                    hasher.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if hasher.hexdigest() != digest:
                raise ValueError(f"{digest[:16]}: RAM copy does not match its digest; not spilled")
            os.replace(temporary, target)
            self._fsync_dir(target.parent)
        except FileNotFoundError:
            return 0
        finally:
            temporary.unlink(missing_ok=True)
        return int(size)

    def clear_staging(self, attempt_id: str) -> None:
        shutil.rmtree(self.staging_root / attempt_id, ignore_errors=True)
        if self.staging_root != self.root / "staging":
            shutil.rmtree(self.root / "staging" / attempt_id, ignore_errors=True)
