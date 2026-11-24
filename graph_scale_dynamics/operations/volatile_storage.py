from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import time

from graph_scale_dynamics.domain.cadence import ticks  # noqa: E402

VOLATILE_STORAGE_CONTRACT = "gsd-volatile-storage-3"


def _folder_scratch() -> Path:
    from graph_scale_dynamics.domain.version import ROOT
    from graph_scale_dynamics.operations import scratch_namespace
    if not scratch_namespace.mounted_here(ROOT):
        scratch_namespace.enter(ROOT)
    return scratch_namespace.scratch_dir(ROOT)


def _is_tmpfs(path: Path) -> bool:
    try:
        target = path.resolve()
        best_mount = None
        best_type = None
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            before, sep, after = line.partition(" - ")
            if not sep:
                continue
            fields = before.split()
            aft = after.split()
            if len(fields) < 5 or not aft:
                continue
            mount = Path(fields[4].replace("\\040", " "))
            try:
                target.relative_to(mount)
            except ValueError:
                continue
            if best_mount is None or len(str(mount)) > len(str(best_mount)):
                best_mount = mount
                best_type = aft[0]
        return best_type in {"tmpfs", "ramfs"}
    except (OSError, ValueError):
        return False


def _usage(path: Path) -> tuple[int | None, int | None, int | None]:
    try:
        usage = shutil.disk_usage(path)
        return int(usage.total), int(usage.used), int(usage.free)
    except OSError:
        return None, None, None


_SCRATCH_USAGE_CACHE: dict[str, object] = {"at": 0.0, "value": 0}
_SCRATCH_USAGE_SECONDS = ticks(1)


def ram_backed_scratch_bytes() -> int:
    now = time.monotonic()
    if now - float(_SCRATCH_USAGE_CACHE["at"]) < _SCRATCH_USAGE_SECONDS:
        return int(_SCRATCH_USAGE_CACHE["value"])  # type: ignore[arg-type]

    roots: list[Path] = []
    explicit = os.environ.get("GSD_VOLATILE_DIR", "").strip()
    if explicit:
        roots.append(Path(explicit))
    if os.name == "posix" and Path("/dev/shm").is_dir():
        roots.append(Path("/dev/shm"))

    seen: set[str] = set()
    total = 0
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            continue
        if key in seen or not root.is_dir() or not _is_tmpfs(root):
            continue
        seen.add(key)
        _, used, _ = _usage(root)
        if used is not None:
            total += int(used)

    _SCRATCH_USAGE_CACHE["at"] = now
    _SCRATCH_USAGE_CACHE["value"] = total
    return total


def choose_volatile_dir(*, required_bytes: int = 0, namespace: str | None = None,
                        allow_persistent_fallback: bool = True) -> dict:
    required = max(0, int(required_bytes or 0))
    explicit = os.environ.get("GSD_VOLATILE_DIR", "").strip()
    candidates: list[tuple[Path, str, bool]] = []
    if explicit:
        candidates.append((Path(explicit), "configured", True))
    else:
        candidates.append((_folder_scratch(), "folder_scratch", False))

    safe_namespace = None
    if namespace:
        digest = hashlib.sha256(str(namespace).encode("utf-8")).hexdigest()[:16]
        safe_namespace = f"gsd-{digest}"

    seen: set[str] = set()
    persistent_fallback: tuple[Path, str] | None = None
    for base, source, operator_declared in candidates:
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        try:
            base.mkdir(parents=True, exist_ok=True)
            tmpfs = _is_tmpfs(base)
            if not tmpfs:
                if persistent_fallback is None:
                    persistent_fallback = (base, source)
                continue
            total, used, free = _usage(base)
            reserve = max(64 * 1024 * 1024, required // 10)
            if required and (free is None or free < required + reserve):
                continue
            target = base / safe_namespace if safe_namespace else base
            target.mkdir(parents=True, exist_ok=True)
            probe = target / f".gsd-write-probe-{os.getpid()}"
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
        except OSError:
            continue
        total, used, free = _usage(base)
        return {
            "contract": VOLATILE_STORAGE_CONTRACT,
            "path": str(target),
            "mount_path": str(base),
            "source": source,
            "tmpfs": bool(tmpfs),
            "volatile": bool(tmpfs),
            "operator_declared": bool(operator_declared),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "required_bytes": required,
            "persistent_fallback": False,
        }

    if allow_persistent_fallback and persistent_fallback is not None:
        base, source = persistent_fallback
        target = base / safe_namespace if safe_namespace else base
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            target = base
        total, used, free = _usage(base)
        return {
            "contract": VOLATILE_STORAGE_CONTRACT,
            "path": str(target), "mount_path": str(base), "source": source,
            "tmpfs": False, "volatile": False, "operator_declared": bool(explicit and base == Path(explicit)),
            "total_bytes": total, "used_bytes": used, "free_bytes": free,
            "required_bytes": required, "persistent_fallback": True,
        }
    return {
        "contract": VOLATILE_STORAGE_CONTRACT,
        "path": None, "mount_path": None, "source": "unavailable",
        "tmpfs": False, "volatile": False, "operator_declared": False,
        "total_bytes": None, "used_bytes": None, "free_bytes": None,
        "required_bytes": required, "persistent_fallback": False,
    }
