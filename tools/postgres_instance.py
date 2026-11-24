#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import posixpath
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations import server_lock
from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir
from graph_scale_dynamics.operations.filesystem_endurance import (
    inspect_cow_placement, resolve_dsm_placement,
)
from graph_scale_dynamics.operations.postgres_tuning import render_settings, resource_plan
from graph_scale_dynamics.domain.cadence import ticks

ENV_FILE = ROOT / ".env.postgres"
INSTANCE_ROOT = ROOT / "instance"
POSTGRES_ROOT = INSTANCE_ROOT / "postgres"
PGDATA = POSTGRES_ROOT / "data"
PGSOCKET = POSTGRES_ROOT / "socket"
PGSUPERVISOR_PID = POSTGRES_ROOT / "supervisor.pid"
PLACEMENT_RECORD = POSTGRES_ROOT / "placement.json"
RUNTIME_ROOT = INSTANCE_ROOT / "container-runtime"
OCI_ROOT = RUNTIME_ROOT / "postgres-17.10-linux-amd64"
OCI_BLOBS = OCI_ROOT / "blobs"
OCI_ROOTFS = OCI_ROOT / "rootfs"
OCI_MARKER = OCI_ROOT / "runtime.json"
BOOTSTRAP_LOCK = INSTANCE_ROOT / ".postgres-bootstrap.lock"
LOG_ROOT = ROOT / "var" / "log"
POSTGRES_LOG = LOG_ROOT / "postgres.log"
TMP_ROOT = ROOT / "var" / "tmp"
POSTGRES_TEMP_TABLESPACE = "gsd_tmpfs"

BUNDLED_ROOT = ROOT / "runtime" / "bootstrap" / "linux-amd64"
BUNDLED_UNSHARE = BUNDLED_ROOT / "unshare"
BUNDLED_LOADER = BUNDLED_ROOT / "ld-linux-x86-64.so.2"
BUNDLED_LIBC = BUNDLED_ROOT / "libc.so.6"
BUNDLED_SHA256 = {
    "unshare": "d82900dfd64b5dd01493d206236575623c2dcf306c466dbe127e171c18cb4614",
    "ld-linux-x86-64.so.2": "438c546d8e8cc48496bf3a95f753051afd9db66a629a74e31a9ded71586b56e0",
    "libc.so.6": "fa430b8f298f817a266046af84a77533185ad6fc4406c7d3787b5a0a0c207826",
}

POSTGRES_VERSION = "17.10"
POSTGRES_ARCH = "linux/amd64"
POSTGRES_REPOSITORY = "library/postgres"
POSTGRES_MANIFEST_DIGEST = (
    "sha256:67870dc097790edf2bd6726658db995dcc830f799d41bb2b78ef07c9a2d5f010"
)
POSTGRES_IMAGE = (
    "docker.io/library/postgres:17.10-bookworm@" + POSTGRES_MANIFEST_DIGEST
)
POSTGRES_BACKEND = "embedded-oci-userns"
REGISTRY = "https://registry-1.docker.io"
TOKEN_URL = "https://auth.docker.io/token"
USER_AGENT = "gsd"


def _secure_write_text(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _fsync_folder(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _secure_replace_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    _secure_write_text(temporary, text)
    try:
        os.replace(temporary, path)
        _fsync_folder(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def bootstrap_lock():
    BOOTSTRAP_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = BOOTSTRAP_LOCK.open("a+")
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "posix":
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _inside_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _assert_local_paths() -> None:
    for path in (
        ENV_FILE, INSTANCE_ROOT, POSTGRES_ROOT, PGDATA, PGSOCKET,
        PGSUPERVISOR_PID, RUNTIME_ROOT, OCI_ROOT, OCI_BLOBS, OCI_ROOTFS,
        OCI_MARKER, BOOTSTRAP_LOCK, LOG_ROOT, POSTGRES_LOG, TMP_ROOT,
        BUNDLED_ROOT, PLACEMENT_RECORD, _server_lock_path(),
    ):
        if not _inside_root(path):
            raise RuntimeError(f"runtime path escaped project root: {path}")


def instance_name(root: Path = ROOT) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", root.name.lower()).strip("-_") or "rr"
    slug = slug[:36].rstrip("-_") or "rr"
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"gsd-{slug}-{digest}"


def _validate_ident(value: str, field: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise ValueError(f"unsafe {field}: {value!r}")
    return value


def _postgres_volatile_root() -> Path:
    chosen = choose_volatile_dir(
        namespace=f"postgres-runtime:{ROOT.resolve()}",
        allow_persistent_fallback=False,
    )
    volatile_path = chosen.get("path")
    if not volatile_path or not chosen.get("volatile"):
        raise RuntimeError(
            "RAM-backed PostgreSQL runtime scratch unavailable; refusing persistent "
            "PostgreSQL temporary files"
        )
    root = Path(str(volatile_path)) / "postgres-runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root


def render_env(*, name: str, password: str,
               database: str = "graph_scale_dynamics", user: str = "rr",
               socket_dir: Path | None = None,
               backend: str = POSTGRES_BACKEND) -> str:
    user = _validate_ident(user, "PostgreSQL user")
    database = _validate_ident(database, "PostgreSQL database")
    socket_dir = PGSOCKET if socket_dir is None else socket_dir
    if not _inside_root(socket_dir):
        raise ValueError(f"PostgreSQL socket must remain below project root: {socket_dir}")
    return "\n".join([
        "# Generated by tools/postgres_instance.py. Keep mode 600.",
        "# Pinned OCI PostgreSQL with bundled rootless namespace runtime.",
        f"INSTANCE_NAME={name}",
        f"POSTGRES_DB={database}",
        f"POSTGRES_USER={user}",
        f"POSTGRES_PASSWORD={password}",
        f"POSTGRES_SOCKET={socket_dir.resolve()}",
        f"POSTGRES_VERSION={POSTGRES_VERSION}",
        f"POSTGRES_BACKEND={backend}",
        f"POSTGRES_MANIFEST={POSTGRES_MANIFEST_DIGEST}",
        "",
    ])


def read_env(path: Path | None = None) -> dict[str, str]:
    path = ENV_FILE if path is None else path
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env(values: dict[str, str]) -> None:
    name = values.get("INSTANCE_NAME", "").strip()
    password = values.get("POSTGRES_PASSWORD", "")
    user = values.get("POSTGRES_USER", "rr").strip() or "rr"
    database = values.get("POSTGRES_DB", "graph_scale_dynamics").strip() or "graph_scale_dynamics"
    if not name:
        raise ValueError("INSTANCE_NAME is missing from .env.postgres")
    if not password:
        raise ValueError("POSTGRES_PASSWORD is missing from .env.postgres")
    _secure_replace_text(ENV_FILE, render_env(name=name, password=password, user=user, database=database))


def _upgrade_config(values: dict[str, str]) -> dict[str, str]:
    if not values.get("INSTANCE_NAME", "").strip():
        raise ValueError(".env.postgres is not a managed folder-local config")
    if not values.get("POSTGRES_PASSWORD", ""):
        raise ValueError("managed .env.postgres is missing POSTGRES_PASSWORD")
    expected_socket = str(PGSOCKET.resolve())
    needs = (
        values.get("POSTGRES_BACKEND") != POSTGRES_BACKEND
        or values.get("POSTGRES_VERSION") != POSTGRES_VERSION
        or values.get("POSTGRES_MANIFEST") != POSTGRES_MANIFEST_DIGEST
        or values.get("POSTGRES_SOCKET") != expected_socket
    )
    if needs:
        _write_env(values)
        values = read_env()
        print("rewrote .env.postgres for this folder's PostgreSQL runtime")
    return values


def _cluster_exists() -> bool:
    return (PGDATA / "PG_VERSION").is_file()


def reset_credentials() -> int:
    _assert_local_paths()
    if not _cluster_exists():
        print(f"no cluster at {PGDATA}; nothing to re-key")
        print("run: python3 tools/postgres_instance.py init")
        return 2

    from graph_scale_dynamics.operations.folder_guard import live_in_folder
    live = live_in_folder(ROOT)
    if live:
        print(f"refused: {live}")
        print("re-keying stops PostgreSQL: end the folder's main.py run or serve first, then run this again")
        return 2

    hba = PGDATA / "pg_hba.conf"
    env_backup = ENV_FILE.read_bytes() if ENV_FILE.exists() else None
    hba_backup = hba.read_bytes() if hba.is_file() else None

    existing = read_env() if ENV_FILE.exists() else {}
    user = _validate_ident(existing.get("POSTGRES_USER", "rr") or "rr", "PostgreSQL user")
    database = (existing.get("POSTGRES_DB") or "graph_scale_dynamics").strip()
    password = secrets.token_urlsafe(32)

    print(f"re-keying role {user!r} on the existing cluster at {PGDATA}")
    print("the campaign data is not touched; only the password changes")
    try:
        if _stop_server():
            raise RuntimeError("PostgreSQL did not stop, so nothing was re-keyed")
        _secure_replace_text(
            ENV_FILE, render_env(name=instance_name(), password=password,
                                 user=user, database=database))
        values = read_env()
        _ensure_cluster(values, hba_policy="trust")
        _start_server(values)
        sqlfile = _postgres_volatile_root() / f"rekey-{os.getpid()}-{secrets.token_hex(4)}.sql"
        literal = password.replace("'", "''")
        _secure_write_text(sqlfile, f"ALTER ROLE {user} WITH PASSWORD '{literal}';\n")
        try:
            result = _run_pg(values, "psql", [
                "-h", str(PGSOCKET), "-U", user, "-d", "postgres",
                "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sqlfile),
            ], capture=True, namespace=False)
        finally:
            sqlfile.unlink(missing_ok=True)
        if result.returncode:
            raise RuntimeError((result.stdout or "ALTER ROLE failed").strip())
    except BaseException:
        if hba_backup is not None:
            hba.write_bytes(hba_backup)
        if env_backup is not None:
            _secure_replace_text(ENV_FILE, env_backup.decode("utf-8"))
        elif ENV_FILE.exists():
            ENV_FILE.unlink()
        raise
    finally:
        if hba.is_file():
            hba.write_text(HBA_POLICIES["scram"], encoding="utf-8")
        _reload_or_stop()

    print(f"re-keyed; credentials rewritten to {ENV_FILE} (mode 600)")
    print("pg_hba.conf is back to scram-sha-256")
    return 0


def init_config() -> int:
    _assert_local_paths()
    if ENV_FILE.exists():
        print(f"refusing to overwrite existing instance config: {ENV_FILE}")
        print("This protects the PostgreSQL cluster already associated with this folder.")
        return 2
    if _cluster_exists():
        print(f"refusing to create a new identity: {PGDATA} already holds a cluster")
        print(f"but its credentials file is missing: {ENV_FILE}")
        print()
        print("Minting a fresh password here would lock this folder out of its own")
        print("database, because the role in that cluster still holds the old one.")
        print("The data is intact. Choose one:")
        print()
        print("  restore .env.postgres from a backup           (keeps the campaign)")
        print("  python3 tools/postgres_instance.py reset-credentials  "
              "(keeps the campaign, mints a new password and applies it to the cluster)")
        print("  rm -rf instance/ var/ .env.postgres          (DESTROYS the campaign, "
              "then re-run; all three together, never one of them)")
        return 3
    password = secrets.token_urlsafe(32)
    _secure_write_text(
        ENV_FILE, render_env(name=instance_name(), password=password)
    )
    _fsync_folder(ENV_FILE.parent)
    for path in (PGDATA, PGSOCKET, RUNTIME_ROOT, LOG_ROOT, TMP_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        PGSOCKET.chmod(0o700)
    print(f"created isolated instance {instance_name()}")
    print(f"PostgreSQL data: {PGDATA}")
    print(f"PostgreSQL socket: {PGSOCKET}")
    print(f"OCI runtime/cache: {RUNTIME_ROOT}")
    print(f"Credentials: {ENV_FILE} (mode 600)")
    return 0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundled_unshare_argv() -> list[str]:
    for name, path in (
        ("unshare", BUNDLED_UNSHARE),
        ("ld-linux-x86-64.so.2", BUNDLED_LOADER),
        ("libc.so.6", BUNDLED_LIBC),
    ):
        if not path.is_file():
            raise RuntimeError(f"bundled namespace runtime is incomplete: missing {path}")
        actual = _sha256_file(path)
        if actual != BUNDLED_SHA256[name]:
            raise RuntimeError(
                f"bundled runtime integrity failure for {name}: {actual}"
            )
    return [
        str(BUNDLED_LOADER), "--library-path", str(BUNDLED_ROOT),
        str(BUNDLED_UNSHARE),
    ]


def _userns_probe() -> tuple[bool, str]:
    if sys.platform != "linux":
        return False, "embedded PostgreSQL container currently requires Linux"
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        return False, (
            f"embedded PostgreSQL payload is linux/amd64; detected architecture {platform.machine()!r}"
        )
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return False, "refusing root execution; run Graph Scale Dynamics as an unprivileged user"
    try:
        uid, gid = _namespace_identity()
        argv = _bundled_unshare_argv() + [
            "--user", f"--map-user={uid}", f"--map-group={gid}",
            "--fork", "--", "/bin/true",
        ]
        probe = subprocess.run(
            argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return False, f"bundled user-namespace probe failed: {type(exc).__name__}: {exc}"
    if probe.returncode:
        detail = (probe.stderr or probe.stdout or "unshare failed").strip()
        return False, (
            "Linux unprivileged user namespaces are unavailable: " + detail
        )
    return True, (
        "bundled util-linux namespace runtime is usable; first database use will "
        "download and verify the pinned PostgreSQL 17.10 OCI layers into this folder"
    )


def runtime_prerequisites() -> tuple[bool, str]:
    return _userns_probe()


def _token() -> str:
    query = urlencode({
        "service": "registry.docker.io",
        "scope": f"repository:{POSTGRES_REPOSITORY}:pull",
    })
    req = Request(f"{TOKEN_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as response:
        data = json.load(response)
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError("Docker Hub token response did not contain an access token")
    return str(token)


def _registry_open(path: str, token: str, *, accept: str | None = None, timeout: int = 60):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    if accept:
        headers["Accept"] = accept
    req = Request(REGISTRY + path, headers=headers)
    return urlopen(req, timeout=timeout)


def _fetch_manifest(token: str) -> tuple[dict, bytes]:
    accept = ", ".join([
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ])
    path = f"/v2/{POSTGRES_REPOSITORY}/manifests/{POSTGRES_MANIFEST_DIGEST}"
    with _registry_open(path, token, accept=accept) as response:
        raw = response.read()
    actual = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual != POSTGRES_MANIFEST_DIGEST:
        raise RuntimeError(
            f"PostgreSQL manifest digest mismatch: expected {POSTGRES_MANIFEST_DIGEST}, got {actual}"
        )
    manifest = json.loads(raw)
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise RuntimeError("pinned PostgreSQL manifest has no layers")
    return manifest, raw


def _download_blob(token: str, digest: str, size: int | None = None) -> Path:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError(f"unsafe OCI blob digest: {digest!r}")
    OCI_BLOBS.mkdir(parents=True, exist_ok=True)
    dest = OCI_BLOBS / digest.replace(":", "-")
    expected = digest.split(":", 1)[1]
    if dest.is_file() and _sha256_file(dest) == expected:
        return dest
    dest.unlink(missing_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    print(f"downloading OCI layer {digest[:19]}…" + (f" ({size / (1024**2):.1f} MiB)" if size else ""))
    h = hashlib.sha256()
    received = 0
    path = f"/v2/{POSTGRES_REPOSITORY}/blobs/{digest}"
    try:
        with _registry_open(path, token, timeout=120) as response, tmp.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                received += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    actual = h.hexdigest()
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"OCI blob digest mismatch for {digest}: got sha256:{actual}")
    if size is not None and received != int(size):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"OCI blob size mismatch for {digest}: expected {size}, got {received}"
        )
    tmp.replace(dest)
    return dest


def _member_rel(name: str) -> PurePosixPath:
    raw = name
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw.startswith("/"):
        raise RuntimeError(f"unsafe path in PostgreSQL OCI layer: {name!r}")
    rel = PurePosixPath(raw)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise RuntimeError(f"unsafe path in PostgreSQL OCI layer: {name!r}")
    return rel


def _safe_rootfs_path(rel: PurePosixPath) -> Path:
    candidate = OCI_ROOTFS.joinpath(*rel.parts)
    try:
        candidate.resolve(strict=False).relative_to(OCI_ROOTFS.resolve())
    except ValueError as exc:
        raise RuntimeError(f"OCI layer path escapes rootfs through a symlink: {rel}") from exc
    return candidate


def _container_link_target(member_name: str, linkname: str, *, hardlink: bool) -> str:
    rel = _member_rel(member_name)
    raw = str(linkname or "")
    if not raw:
        raise RuntimeError(f"empty link target in PostgreSQL OCI layer: {member_name!r}")

    if hardlink:
        target = posixpath.normpath('/' + raw.lstrip('/'))
        if target == '/' or target.startswith('/../'):
            raise RuntimeError(f"unsafe hard-link target in PostgreSQL OCI layer: {raw!r}")
        return target.lstrip('/')

    parent = '/' + '/'.join(rel.parts[:-1])
    if raw.startswith('/'):
        target = posixpath.normpath(raw)
    else:
        target = posixpath.normpath(posixpath.join(parent, raw))
    if not target.startswith('/'):
        target = '/' + target
    relative = posixpath.relpath(target, start=parent or '/')
    return relative


def _oci_extract_filter(member: tarfile.TarInfo, destination: str | os.PathLike[str]):
    if member.issym():
        member = member.replace(
            linkname=_container_link_target(member.name, member.linkname, hardlink=False)
        )
    elif member.islnk():
        member = member.replace(
            linkname=_container_link_target(member.name, member.linkname, hardlink=True)
        )
    return tarfile.data_filter(member, destination)


def _delete_whiteout_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _extract_layer(blob: Path) -> None:
    with tarfile.open(blob, mode="r:*") as archive:
        regular: list[tarfile.TarInfo] = []
        for member in archive.getmembers():
            rel = _member_rel(member.name)
            name = rel.name
            parent_rel = PurePosixPath(*rel.parts[:-1]) if rel.parts[:-1] else PurePosixPath(".")
            parent = OCI_ROOTFS if str(parent_rel) == "." else _safe_rootfs_path(parent_rel)
            if name == ".wh..wh..opq":
                if parent.is_dir():
                    for child in parent.iterdir():
                        try:
                            child.resolve(strict=False).relative_to(OCI_ROOTFS.resolve())
                        except ValueError as exc:
                            raise RuntimeError(f"unsafe opaque whiteout target: {child}") from exc
                        _delete_whiteout_target(child)
                continue
            if name.startswith(".wh."):
                target_rel = PurePosixPath(*(rel.parts[:-1] + (name[4:],)))
                _delete_whiteout_target(_safe_rootfs_path(target_rel))
                continue
            if member.ischr() or member.isblk() or member.isfifo():
                continue
            regular.append(member)
        archive.extractall(OCI_ROOTFS, members=regular, filter=_oci_extract_filter)


def _loader_and_libdirs() -> tuple[Path, list[Path]]:
    candidates = [
        OCI_ROOTFS / "lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
        OCI_ROOTFS / "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    ]
    loader = next((p for p in candidates if p.is_file()), None)
    if loader is None:
        raise RuntimeError("PostgreSQL OCI rootfs is missing its amd64 dynamic loader")
    libdirs = [p for p in (
        OCI_ROOTFS / "lib/x86_64-linux-gnu",
        OCI_ROOTFS / "usr/lib/x86_64-linux-gnu",
        OCI_ROOTFS / "usr/lib/postgresql/17/lib",
        OCI_ROOTFS / "lib",
        OCI_ROOTFS / "usr/lib",
    ) if p.is_dir()]
    return loader, libdirs


def _named_loader(loader: Path, program: str) -> Path:
    directory = OCI_ROOTFS.parent / "named-loaders"
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / f"gsd-{program}"
    if link.is_symlink() and Path(os.readlink(link)) == Path(loader):
        return link
    link.unlink(missing_ok=True)
    link.symlink_to(loader)
    return link


def _wrapper_script(loader: Path, library_path: str, real: Path, program: str) -> str:
    named = _named_loader(loader, program)
    return (
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(named))} --library-path {shlex.quote(library_path)} "
        f"--argv0 \"$0\" {shlex.quote(str(real))} \"$@\"\n"
    )


def _wrap_postgres_binaries() -> None:
    bin_dir = OCI_ROOTFS / "usr/lib/postgresql/17/bin"
    if not (bin_dir / "postgres").exists() and not (bin_dir / "postgres.gsd-real").exists():
        raise RuntimeError("pinned PostgreSQL OCI rootfs does not contain PostgreSQL 17 binaries")
    loader, libdirs = _loader_and_libdirs()
    library_path = ":".join(str(p) for p in libdirs)
    for path in sorted(bin_dir.iterdir()):
        if path.name.endswith(".gsd-real") or path.is_symlink() or not path.is_file():
            continue
        real = path.with_name(path.name + ".gsd-real")
        if real.exists():
            pass
        else:
            try:
                magic = path.open("rb").read(4)
            except OSError:
                continue
            if magic != b"\x7fELF":
                continue
            path.replace(real)
        path.write_text(_wrapper_script(loader, library_path, real, path.name), encoding="utf-8")
        path.chmod(0o755)
    for real in sorted(bin_dir.glob("*.gsd-real")):
        path = real.with_name(real.name[:-8])
        path.write_text(_wrapper_script(loader, library_path, real, path.name), encoding="utf-8")
        path.chmod(0o755)


def _runtime_complete() -> bool:
    try:
        marker = json.loads(OCI_MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        marker.get("manifest") == POSTGRES_MANIFEST_DIGEST
        and marker.get("arch") == POSTGRES_ARCH
        and (OCI_ROOTFS / "usr/lib/postgresql/17/bin/postgres").is_file()
    )


def ensure_runtime_payload() -> None:
    _assert_local_paths()
    if system_bin_dir() is not None:
        print(f"using host PostgreSQL binaries from {SYSTEM_BIN_ENV}={system_bin_dir()}; pinned image not required")
        return
    if _runtime_complete():
        _wrap_postgres_binaries()
        return
    OCI_ROOT.mkdir(parents=True, exist_ok=True)
    OCI_BLOBS.mkdir(parents=True, exist_ok=True)
    try:
        token = _token()
        manifest, _raw = _fetch_manifest(token)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "cannot fetch the pinned PostgreSQL OCI manifest from Docker Hub; "
            "the managed runtime never falls back to host PostgreSQL or a system container daemon: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    layer_paths: list[Path] = []
    for layer in manifest["layers"]:
        digest = str(layer.get("digest", ""))
        size = layer.get("size")
        layer_paths.append(_download_blob(token, digest, int(size) if size is not None else None))
    if OCI_ROOTFS.exists():
        shutil.rmtree(OCI_ROOTFS)
    OCI_ROOTFS.mkdir(parents=True, exist_ok=True)
    for path in layer_paths:
        print(f"extracting {path.name[:26]}…")
        _extract_layer(path)
    _wrap_postgres_binaries()
    marker = {
        "version": POSTGRES_VERSION,
        "arch": POSTGRES_ARCH,
        "manifest": POSTGRES_MANIFEST_DIGEST,
        "image": POSTGRES_IMAGE,
        "layers": [str(layer["digest"]) for layer in manifest["layers"]],
    }
    tmp = OCI_MARKER.with_suffix(".tmp")
    tmp.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OCI_MARKER)
    print(f"verified PostgreSQL {POSTGRES_VERSION} OCI runtime: {OCI_ROOTFS}")


SYSTEM_BIN_ENV = "GSD_POSTGRES_SYSTEM_BIN"


def system_bin_dir() -> Path | None:
    value = str(os.environ.get(SYSTEM_BIN_ENV, "")).strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if not (path / "postgres").is_file() or not (path / "initdb").is_file():
        raise RuntimeError(f"{SYSTEM_BIN_ENV}={path} does not contain postgres and initdb")
    return path


def _expected_major() -> str:
    override = system_bin_dir()
    if override is None:
        return "17"
    try:
        out = subprocess.run([str(override / "postgres"), "--version"], capture_output=True,
                             text=True, timeout=20).stdout
        return out.strip().split()[-1].split(".")[0].lstrip("(")
    except (OSError, subprocess.SubprocessError, IndexError):
        return "17"


def runtime_version_label() -> str:
    override = system_bin_dir()
    return POSTGRES_VERSION if override is None else f"host {_expected_major()}.x"


def _bin_dir() -> Path:
    override = system_bin_dir()
    return override if override is not None else OCI_ROOTFS / "usr/lib/postgresql/17/bin"


def _pg_bin(name: str) -> Path:
    path = _bin_dir() / name
    if not path.is_file():
        raise RuntimeError(f"PostgreSQL runtime is missing {name}: {path}")
    return path


def _project_env(values: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER",
        "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE", "PGSYSCONFDIR",
        "DATABASE_URL",
    ):
        env.pop(key, None)
    home = POSTGRES_ROOT / "home"
    home.mkdir(parents=True, exist_ok=True)
    postgres_tmp = _postgres_volatile_root()
    env.update({
        "HOME": str(home),
        "TMPDIR": str(postgres_tmp),
        "TMP": str(postgres_tmp),
        "TEMP": str(postgres_tmp),
        "PGPASSWORD": values.get("POSTGRES_PASSWORD", ""),
        "PATH": str(_bin_dir()) + ":/usr/bin:/bin",
        "LC_ALL": "C",
        "LANG": "C",
    })
    return env


def _namespace_identity() -> tuple[int, int]:
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise RuntimeError("embedded PostgreSQL requires POSIX user identities")
    uid, gid = int(os.getuid()), int(os.getgid())
    if uid == 0:
        raise RuntimeError("the managed PostgreSQL runtime refuses root execution")
    return uid, gid


def _namespace_argv(command: list[str], *, server: bool) -> list[str]:
    uid, gid = _namespace_identity()
    argv = _bundled_unshare_argv() + [
        "--user", f"--map-user={uid}", f"--map-group={gid}",
    ]
    if server:
        argv += [
            "--pid", "--ipc", "--uts", "--net", "--fork", "--kill-child=SIGINT",
        ]
    else:
        argv += ["--fork"]
    return argv + ["--"] + command


def _run_pg(values: dict[str, str], name: str, args: list[str], *, capture: bool = False,
            namespace: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [str(_pg_bin(name))] + args
    if namespace:
        cmd = _namespace_argv(cmd, server=False)
    return subprocess.run(
        cmd, cwd=ROOT, env=_project_env(values),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )


def _supported_wal_compression(values: dict[str, str]) -> str:
    requested = str(os.environ.get("GSD_PG_WAL_COMPRESSION", "zstd")).strip().lower() or "zstd"
    if requested != "zstd":
        return requested
    try:
        result = _run_pg(values, "postgres", [
            "-D", str(PGDATA), "-C", "wal_compression", "-c", "wal_compression=zstd",
        ], capture=True)
        if result.returncode == 0 and "zstd" in str(result.stdout or "").lower():
            return "zstd"
    except Exception:
        pass
    return "on"


def _volatile_root_or_none() -> Path | None:
    try:
        return _postgres_volatile_root()
    except RuntimeError:
        return None


def _apply_dsm_placement() -> dict[str, object]:
    requested = str(os.environ.get("GSD_PG_DSM_TYPE", "posix")).strip().lower() or "posix"
    if requested not in {"posix", "mmap", "sysv"}:
        raise RuntimeError(f"invalid GSD_PG_DSM_TYPE={requested!r}")
    placement = resolve_dsm_placement(
        PGDATA, volatile_root=_volatile_root_or_none(), requested=requested,
    )
    target = placement.get("relocated_dynshmem")
    dynshmem = PGDATA / "pg_dynshmem"
    if target:
        if dynshmem.is_symlink():
            if os.readlink(dynshmem) != str(target):
                dynshmem.unlink()
        elif dynshmem.is_dir():
            shutil.rmtree(dynshmem)
        if not dynshmem.exists():
            dynshmem.symlink_to(str(target), target_is_directory=True)
    elif dynshmem.is_symlink():
        dynshmem.unlink()
        dynshmem.mkdir(parents=True, exist_ok=True)
    return placement


HBA_POLICIES: dict[str, str] = {
    "scram": ("# Unix-socket-only; network namespace has no interfaces.\n"
              "local all all scram-sha-256\n"),
    "trust": ("# TEMPORARY: credential recovery in progress "
              "(tools/postgres_instance.py reset-credentials).\n"
              "# If this file still says trust, the recovery did not finish; "
              "restore scram-sha-256.\n"
              "local all all trust\n"),
}


def _max_connections() -> int:
    from graph_scale_dynamics.scheduling.concurrency import (
        CONNECTIONS_PER_SLOT, CONNECTION_RESERVE, ramp_ceiling)
    override = os.environ.get("GSD_MAX_WORKERS")
    try:
        logical = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        logical = max(1, os.cpu_count() or 1)
    ceiling = ramp_ceiling(baseline=1, logical=logical,
                           override=int(override) if override else None)
    return max(100, ceiling * CONNECTIONS_PER_SLOT + CONNECTION_RESERVE)


def _configure_cluster(values: dict[str, str], *, hba_policy: str = "scram") -> None:
    config = PGDATA / "postgresql.conf"
    socket_value = str(PGSOCKET.resolve()).replace("'", "''")
    wal_compression = _supported_wal_compression(values)
    placement = _apply_dsm_placement()
    plan = resource_plan()
    synchronous_commit = str(os.environ.get("GSD_PG_SYNCHRONOUS_COMMIT", "off")).strip().lower() or "off"
    if synchronous_commit not in {"on", "off", "local", "remote_write", "remote_apply"}:
        raise RuntimeError(f"invalid GSD_PG_SYNCHRONOUS_COMMIT={synchronous_commit!r}")
    block = (
        "\n# Graph Ensemble Scale Dynamics folder-contained PostgreSQL runtime\n"
        "listen_addresses = ''\n"
        f"max_connections = {_max_connections()}\n"
        f"unix_socket_directories = '{socket_value}'\n"
        "unix_socket_permissions = 0700\n"
        f"dynamic_shared_memory_type = {placement['dynamic_shared_memory_type']}\n"
        "logging_collector = off\n"
        f"synchronous_commit = {synchronous_commit}\n"
        f"wal_compression = {wal_compression}\n"
        "checkpoint_timeout = '30min'\n"
        "checkpoint_completion_target = 0.9\n"
        "max_wal_size = '16GB'\n"
        "min_wal_size = '2GB'\n"
        f"wal_writer_delay = '{int(ticks(1) * 1000)}ms'\n"
        "wal_writer_flush_after = '4MB'\n"
        "wal_recycle = on\n"
        "wal_init_zero = off\n"
        "bgwriter_delay = '200ms'\n"
        "bgwriter_lru_maxpages = 1000\n"
        "backend_flush_after = '2MB'\n"
        "bgwriter_flush_after = '2MB'\n"
        "checkpoint_flush_after = '1MB'\n"
        "autovacuum_naptime = '60s'\n"
        "autovacuum_vacuum_cost_delay = '10ms'\n"
        "\n# host-derived resource policy\n"
        + render_settings(plan["settings"])
    )
    cow = inspect_cow_placement(PGDATA)
    record = {
        "dsm": placement,
        "cow": cow,
        "resource_budget": plan["budget"],
        "settings": plan["settings"] | {"max_connections": str(_max_connections())},
    }
    tmp = PLACEMENT_RECORD.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(PLACEMENT_RECORD)
    for advisory in list(placement.get("advisories") or []) + list(cow.get("advisories") or []):
        print(f"storage-endurance advisory: {advisory}")

    text = config.read_text(encoding="utf-8")
    cut = text.find("\n# Graph Ensemble Scale Dynamics folder-contained PostgreSQL runtime")
    if cut >= 0:
        text = text[:cut].rstrip() + "\n"
    config.write_text(text + block, encoding="utf-8")
    hba = PGDATA / "pg_hba.conf"
    hba.write_text(HBA_POLICIES[hba_policy], encoding="utf-8")


def _ensure_cluster(values: dict[str, str], *, hba_policy: str = "scram") -> None:
    PGDATA.mkdir(parents=True, exist_ok=True)
    PGSOCKET.mkdir(parents=True, exist_ok=True)
    PGSOCKET.chmod(0o700)
    if (PGDATA / "PG_VERSION").is_file():
        version = (PGDATA / "PG_VERSION").read_text(encoding="utf-8").strip()
        expected = _expected_major()
        if version != expected:
            raise RuntimeError(f"refusing PGDATA major-version drift: expected {expected}, found {version!r}")
        _configure_cluster(values, hba_policy=hba_policy)
        return
    if any(PGDATA.iterdir()):
        raise RuntimeError(f"refusing to initialize non-empty PostgreSQL data directory: {PGDATA}")
    user = _validate_ident(values.get("POSTGRES_USER", "rr"), "PostgreSQL user")
    runtime_tmp = _postgres_volatile_root()
    pwfile = runtime_tmp / f"initdb-password-{os.getpid()}-{secrets.token_hex(4)}"
    _secure_write_text(pwfile, values["POSTGRES_PASSWORD"] + "\n")
    try:
        result = _run_pg(values, "initdb", [
            "-D", str(PGDATA),
            "-U", user,
            "--pwfile", str(pwfile),
            "--auth-local=scram-sha-256",
            "--auth-host=reject",
            "--encoding=UTF8",
            "--locale=C",
            "--no-sync",
        ], capture=True)
    finally:
        pwfile.unlink(missing_ok=True)
    if result.returncode:
        raise RuntimeError((result.stdout or "initdb failed").strip())
    _configure_cluster(values, hba_policy=hba_policy)
    print(f"initialized PostgreSQL {runtime_version_label()} cluster: {PGDATA}")


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    proc = Path("/proc") / str(pid) / "cmdline"
    try:
        cmdline = proc.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return True
    if "unshare" not in cmdline:
        return False
    return _names_folder(cmdline, ROOT) or _runs_in_this_folder(pid)


def _names_folder(cmdline: str, folder: Path) -> bool:
    import re
    return re.search(re.escape(str(folder.resolve())) + r"(?![^/\s])", cmdline) is not None


def _runs_in_this_folder(pid: int) -> bool:
    return _runs_in(pid, ROOT)


def _runs_in(pid: int, folder: Path) -> bool:
    try:
        here, there = folder.resolve().stat(), os.stat(f"/proc/{pid}/cwd")
    except OSError:
        return False
    return (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)


def _read_supervisor_pid() -> int | None:
    try:
        pid = int(PGSUPERVISOR_PID.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def _server_lock_path() -> Path:
    return ROOT / "instance" / "postgres" / server_lock.LOCK_NAME


def _running_supervisor() -> int | None:
    return server_lock.holder(_server_lock_path()) or _read_supervisor_pid()


def _server_running() -> bool:
    return bool(server_lock.held(_server_lock_path())) or _read_supervisor_pid() is not None


def _reload_or_stop() -> None:
    supervisor = _running_supervisor()
    if supervisor is None:
        return
    postmaster = _postgres_postmaster_child(supervisor)
    if postmaster is not None:
        try:
            os.kill(postmaster, signal.SIGHUP)
            print(f"PostgreSQL (postmaster {postmaster}) told to read pg_hba.conf again")
            return
        except OSError:
            pass
    print("the running PostgreSQL could not be told to read pg_hba.conf again; stopping it")
    if _stop_server():
        print("PostgreSQL did not stop: stop it before anything else (python3 tools/postgres_instance.py stop)")


def _wait_ready(values: dict[str, str], *, database: str = "postgres", timeout: float = 90.0) -> None:
    user = _validate_ident(values.get("POSTGRES_USER", "rr"), "PostgreSQL user")
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        probe = _run_pg(values, "pg_isready", [
            "-h", str(PGSOCKET), "-U", user, "-d", database,
        ], capture=True, namespace=False)
        last = (probe.stdout or "").strip()
        if probe.returncode == 0:
            return
        if not _server_running():
            break
        time.sleep(0.5)
    raise RuntimeError(
        f"PostgreSQL did not become ready within {timeout:.0f}s" + (f": {last}" if last else "")
    )


def _ensure_database(values: dict[str, str]) -> None:
    user = _validate_ident(values.get("POSTGRES_USER", "rr"), "PostgreSQL user")
    database = _validate_ident(values.get("POSTGRES_DB", "graph_scale_dynamics"), "PostgreSQL database")
    query = _run_pg(values, "psql", [
        "-h", str(PGSOCKET), "-U", user, "-d", "postgres",
        "-Atqc", f"SELECT 1 FROM pg_database WHERE datname = '{database}'",
    ], capture=True, namespace=False)
    if query.returncode:
        raise RuntimeError((query.stdout or "cannot inspect PostgreSQL databases").strip())
    if (query.stdout or "").strip() == "1":
        return
    created = _run_pg(values, "createdb", [
        "-h", str(PGSOCKET), "-U", user, database,
    ], capture=True, namespace=False)
    if created.returncode:
        raise RuntimeError((created.stdout or f"cannot create database {database}").strip())


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ensure_tmpfs_temp_tablespace(values: dict[str, str]) -> Path:
    volatile = choose_volatile_dir(
        namespace=f"postgres-temp-tablespace:{ROOT.resolve()}",
        allow_persistent_fallback=False,
    )
    volatile_path = volatile.get("path")
    if not volatile_path or not volatile.get("volatile"):
        raise RuntimeError(
            "RAM-backed PostgreSQL temp tablespace unavailable; refusing to spill "
            "query work files into PGDATA"
        )
    target = Path(str(volatile_path)) / "postgres-temp-tablespace"

    def psql(sql: str, failure: str) -> None:
        result = _run_pg(values, "psql", [
            "-h", str(PGSOCKET), "-U", values.get("POSTGRES_USER", "rr"), "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-Atqc", sql,
        ], capture=True, namespace=False)
        if result.returncode:
            raise RuntimeError((result.stdout or failure).strip())

    psql("ALTER SYSTEM RESET temp_tablespaces", "cannot reset PostgreSQL temp_tablespaces")
    psql("SELECT pg_reload_conf()", "cannot reload PostgreSQL configuration")
    psql(
        f"DROP TABLESPACE IF EXISTS {POSTGRES_TEMP_TABLESPACE}",
        "cannot drop old PostgreSQL temp tablespace",
    )

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    psql(
        f"CREATE TABLESPACE {POSTGRES_TEMP_TABLESPACE} "
        f"LOCATION {_sql_literal(str(target.resolve()))}",
        "cannot create PostgreSQL tmpfs temp tablespace",
    )
    psql(
        f"ALTER SYSTEM SET temp_tablespaces = {_sql_literal(POSTGRES_TEMP_TABLESPACE)}",
        "cannot set PostgreSQL tmpfs temp tablespace",
    )
    psql("SELECT pg_reload_conf()", "cannot reload PostgreSQL temp-tablespace configuration")
    return target


_RESTART_ONLY_GUCS = (
    "dynamic_shared_memory_type", "shared_buffers", "min_dynamic_shared_memory",
    "max_connections", "max_worker_processes", "huge_pages",
)


def _warn_on_stale_runtime_placement(values: dict[str, str]) -> None:
    try:
        record = json.loads(PLACEMENT_RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    desired = dict(record.get("settings") or {})
    desired["dynamic_shared_memory_type"] = str(
        (record.get("dsm") or {}).get("dynamic_shared_memory_type") or ""
    )
    stale: list[str] = []
    for guc in _RESTART_ONLY_GUCS:
        want = str(desired.get(guc) or "").strip().strip("'")
        if not want:
            continue
        probe = _run_pg(values, "psql", [
            "-h", str(PGSOCKET), "-U", values.get("POSTGRES_USER", "rr"), "-d", "postgres",
            "-Atqc", f"SHOW {guc}",
        ], capture=True, namespace=False)
        if probe.returncode:
            continue
        live = str(probe.stdout or "").strip()
        if live and live.lower().replace(" ", "") != want.lower().replace(" ", ""):
            stale.append(f"{guc}: running={live} configured={want}")
    if stale:
        print(
            "storage-endurance advisory: the running PostgreSQL server predates this "
            "configuration and is still using start-time values: " + "; ".join(stale)
        )
        print(
            "storage-endurance advisory: run 'python3 tools/postgres_instance.py stop' then "
            "'up' during a maintenance window to adopt them."
        )


def _placement_summary() -> str:
    try:
        record = json.loads(PLACEMENT_RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "dsm=unknown"
    dsm = record.get("dsm") or {}
    settings = record.get("settings") or {}
    return (
        f"dsm={dsm.get('dynamic_shared_memory_type')}/{dsm.get('placement')}; "
        f"shared_buffers={settings.get('shared_buffers')}; work_mem={settings.get('work_mem')}"
    )


def recreate_missing_tablespace_dirs(pgdata: Path) -> list[Path]:
    tblspc = Path(pgdata) / "pg_tblspc"
    if not tblspc.is_dir():
        return []
    recreated: list[Path] = []
    for link in sorted(tblspc.iterdir()):
        if not link.is_symlink():
            continue
        try:
            target = Path(os.readlink(link))
        except OSError:
            continue
        if target.exists():
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"warning: cannot recreate tablespace location {target}: {exc}")
            continue
        recreated.append(target)
    return recreated


def _start_server(values: dict[str, str], *, hba_policy: str = "scram") -> None:
    if _server_running():
        _wait_ready(values, database="postgres", timeout=30)
        _ensure_database(values)
        temp_tablespace = _ensure_tmpfs_temp_tablespace(values)
        _wait_ready(values, database=values.get("POSTGRES_DB", "graph_scale_dynamics"), timeout=30)
        _warn_on_stale_runtime_placement(values)
        print(
            f"PostgreSQL {runtime_version_label()} already running; socket={PGSOCKET}; "
            f"temp spill={temp_tablespace}; {_placement_summary()}"
        )
        return
    lock = server_lock.take(_server_lock_path())
    if lock is None:
        raise RuntimeError(f"refusing to start PostgreSQL: {_server_lock_path()} is held by another process, "
                           f"so a server already runs on {PGDATA}")
    try:
        PGSUPERVISOR_PID.unlink(missing_ok=True)
        recreated = recreate_missing_tablespace_dirs(PGDATA)
        if recreated:
            print(
                "recreated missing tablespace director"
                + ("y" if len(recreated) == 1 else "ies")
                + " before start (roadmap 247 §5.1): " + ", ".join(str(r) for r in recreated)
            )
        runtime_log = _postgres_volatile_root() / "postgres.log"
        cmd = _namespace_argv([
            str(_pg_bin("postgres")), "-D", str(PGDATA),
        ], server=True)
        with runtime_log.open("ab", buffering=0) as log:
            proc = subprocess.Popen(
                cmd, cwd=ROOT, env=_project_env(values), stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(lock,),
            )
        server_lock.write_record(lock, {
            "pid": proc.pid, "log": str(runtime_log), "data": str(PGDATA.resolve()),
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        PGSUPERVISOR_PID.write_text(str(proc.pid) + "\n", encoding="ascii")
    finally:
        os.close(lock)
    _wait_ready(values, database="postgres")
    _ensure_database(values)
    temp_tablespace = _ensure_tmpfs_temp_tablespace(values)
    _wait_ready(values, database=values.get("POSTGRES_DB", "graph_scale_dynamics"), timeout=30)
    print(
        f"PostgreSQL {runtime_version_label()} ready in embedded user-namespace container; "
        f"socket={PGSOCKET}; temp spill={temp_tablespace}; {_placement_summary()}"
    )


def _process_exists(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _direct_child_pids(pid: int) -> list[int]:
    try:
        text = (Path("/proc") / str(pid) / "task" / str(pid) / "children").read_text(
            encoding="ascii"
        )
    except OSError:
        return []
    result = []
    for token in text.split():
        try:
            child = int(token)
        except ValueError:
            continue
        if child > 1:
            result.append(child)
    return result


def _postgres_postmaster_child(supervisor_pid: int) -> int | None:
    pgdata = str(PGDATA.resolve())
    for child in _direct_child_pids(supervisor_pid):
        try:
            cmdline = (Path("/proc") / str(child) / "cmdline").read_bytes().replace(
                b"\0", b" "
            ).decode("utf-8", "replace")
        except OSError:
            continue
        if "postgres" not in cmdline or " -D " not in f" {cmdline} ":
            continue
        if pgdata in cmdline or _runs_in(child, PGDATA):
            return child
    return None


def _stop_server(timeout: float = 30.0) -> int:
    supervisor_pid = _running_supervisor()
    if supervisor_pid is None:
        if server_lock.held(_server_lock_path()):
            print(f"{_server_lock_path()} is held by a process this user cannot see: PostgreSQL may still run on "
                  f"{PGDATA}")
            return 2
        PGSUPERVISOR_PID.unlink(missing_ok=True)
        return 0

    postmaster_pid = _postgres_postmaster_child(supervisor_pid)
    target_pid = postmaster_pid if postmaster_pid is not None else supervisor_pid
    try:
        os.kill(target_pid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.monotonic() + timeout
    fast_deadline = time.monotonic() + min(10.0, max(2.0, timeout / 3.0))
    fast_sent = False
    while time.monotonic() < deadline:
        if not _server_running():
            PGSUPERVISOR_PID.unlink(missing_ok=True)
            return 0
        if (postmaster_pid is not None and not fast_sent
                and _process_exists(postmaster_pid) and time.monotonic() >= fast_deadline):
            try:
                os.kill(postmaster_pid, signal.SIGINT)
                fast_sent = True
            except OSError:
                pass
        if postmaster_pid is not None and not _process_exists(postmaster_pid):
            try:
                os.kill(supervisor_pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.2)
    detail = f" (postmaster {postmaster_pid})" if postmaster_pid is not None else ""
    print(
        f"PostgreSQL supervisor {supervisor_pid}{detail} did not stop within {timeout:.0f}s"
    )
    return 2


def _tail_log(lines: int = 200) -> None:
    recorded = server_lock.read_record(_server_lock_path()).get("log")
    try:
        runtime_log = Path(recorded) if recorded else _postgres_volatile_root() / "postgres.log"
    except RuntimeError:
        runtime_log = POSTGRES_LOG
    if not runtime_log.is_file():
        print("PostgreSQL log has not been created yet")
        return
    content = runtime_log.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(content[-max(1, lines):]))


def runtime_command(action: str, extra: list[str]) -> int:
    _assert_local_paths()
    if not ENV_FILE.is_file():
        if action == "stop" and not _server_running():
            print("not running (no .env.postgres and no live supervisor)")
            return 0
        print("missing .env.postgres; run: python3 tools/postgres_instance.py init")
        return 2
    values = _upgrade_config(read_env())
    backend = values.get("POSTGRES_BACKEND", "")
    if backend != POSTGRES_BACKEND:
        print(f"refusing unsupported PostgreSQL backend {backend!r}; expected {POSTGRES_BACKEND}")
        return 2
    if action == "status":
        running, pid = _server_running(), _running_supervisor()
        print("running" if running else "stopped", f"backend={POSTGRES_BACKEND}", f"pid={pid or '-'}")
        return 0 if running else 1
    if action == "logs":
        _tail_log()
        return 0
    if action in {"stop", "down"}:
        return _stop_server()
    if action != "up":
        raise ValueError(action)
    ok, detail = runtime_prerequisites()
    if not ok:
        print(detail)
        print("No sudo, host PostgreSQL, Docker/Podman daemon, or OS-state fallback will be attempted.")
        return 2
    try:
        ensure_runtime_payload()
        _ensure_cluster(values)
        _start_server(values)
    except Exception as exc:
        print(f"folder-contained PostgreSQL startup failed: {type(exc).__name__}: {exc}")
        return 2
    return 0


def ensure_instance() -> int:
    with bootstrap_lock():
        if not ENV_FILE.is_file():
            rc = init_config()
            if rc != 0:
                return rc
        return runtime_command("up", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/postgres_instance.py: see docs/TOOLS.md")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create this folder's isolated PostgreSQL identity")
    sub.add_parser("reset-credentials",
                   help="re-key an existing cluster whose .env.postgres was lost "
                        "(keeps all campaign data)")
    sub.add_parser("ensure", help="prepare pinned OCI runtime, initialize/start PostgreSQL, wait ready")
    sub.add_parser("prepare-runtime", help="download and verify the pinned OCI image without starting PostgreSQL")
    sub.add_parser("runtime", help="probe bundled unprivileged namespace support without network access")
    for name in ("up", "down", "stop", "status", "logs"):
        sub.add_parser(name)
    args, extra = parser.parse_known_args(argv)
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.command == "init":
        return init_config()
    if args.command == "reset-credentials":
        with bootstrap_lock():
            return reset_credentials()
    if args.command == "up":
        with bootstrap_lock():
            return runtime_command("up", [])
    if args.command == "ensure":
        return ensure_instance()
    if args.command == "prepare-runtime":
        ok, detail = runtime_prerequisites()
        if not ok:
            print("not ready: " + detail)
            return 2
        try:
            ensure_runtime_payload()
        except Exception as exc:
            print(f"runtime preparation failed: {type(exc).__name__}: {exc}")
            return 2
        return 0
    if args.command == "runtime":
        ok, detail = runtime_prerequisites()
        print(("ready: " if ok else "not ready: ") + detail)
        return 0 if ok else 2
    return runtime_command(args.command, [])


if __name__ == "__main__":
    raise SystemExit(main())
