from __future__ import annotations

import array
import fcntl
import os
import shutil
from pathlib import Path
from typing import Any

FILESYSTEM_ENDURANCE_CONTRACT = "gsd-filesystem-endurance-1"

_FS_IOC_GETFLAGS = 0x80086601
_FS_NOCOW_FL = 0x00800000
_FS_COMPR_FL = 0x00000004

_COW_FILESYSTEMS = frozenset({"btrfs", "zfs", "bcachefs"})

_MIN_POSIX_SHM_BYTES = 512 * 1024 * 1024


def _mount_type(path: Path) -> tuple[str | None, str | None]:
    try:
        target = path.resolve()
    except OSError:
        return None, None
    best_mount: str | None = None
    best_type: str | None = None
    try:
        raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return None, None
    for line in raw.splitlines():
        before, sep, after = line.partition(" - ")
        if not sep:
            continue
        fields = before.split()
        tail = after.split()
        if len(fields) < 5 or not tail:
            continue
        mount = Path(fields[4].replace("\\040", " "))
        try:
            target.relative_to(mount)
        except ValueError:
            continue
        if best_mount is None or len(str(mount)) > len(best_mount):
            best_mount = str(mount)
            best_type = tail[0]
    return best_mount, best_type


def _inode_flags(path: Path) -> int | None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return None
    try:
        buffer = array.array("l", [0])
        fcntl.ioctl(fd, _FS_IOC_GETFLAGS, buffer, True)
        return int(buffer[0])
    except OSError:
        return None
    finally:
        os.close(fd)


def inspect_cow_placement(pgdata: Path) -> dict[str, Any]:
    pgdata = Path(pgdata)
    probe = pgdata if pgdata.is_dir() else pgdata.parent
    mount_point, filesystem = _mount_type(probe)
    flags = _inode_flags(probe) if probe.is_dir() else None
    cow_filesystem = bool(filesystem and filesystem in _COW_FILESYSTEMS)
    nodatacow = None if flags is None else bool(flags & _FS_NOCOW_FL)
    compressed = None if flags is None else bool(flags & _FS_COMPR_FL)

    advisories: list[str] = []
    if cow_filesystem and nodatacow is False:
        advisories.append(
            f"PGDATA is on {filesystem} with copy-on-write active; every 8 kB page rewrite "
            "allocates a new extent plus checksum/metadata updates. Run "
            "'python3 tools/gsd_pgdata_cow.py migrate' with the cluster stopped to move PGDATA "
            "into a nodatacow directory."
        )
    if cow_filesystem and compressed:
        advisories.append(
            "PGDATA carries the filesystem compression attribute; compressed extents cannot be "
            "rewritten in place and increase write amplification for a database workload."
        )
    if filesystem == "btrfs":
        advisories.append(
            "Btrfs defaults to the DUP metadata profile on a single device, writing every "
            "metadata block twice. 'btrfs balance start -mconvert=single' halves metadata writes "
            "at the cost of metadata redundancy; evaluate against your backup posture."
        )
        advisories.append(
            "Mount the PGDATA filesystem with 'noatime' so read-heavy reporting scans do not "
            "dirty inodes."
        )
    return {
        "contract": FILESYSTEM_ENDURANCE_CONTRACT,
        "path": str(pgdata),
        "mount_point": mount_point,
        "filesystem": filesystem,
        "copy_on_write_filesystem": cow_filesystem,
        "inode_flags": flags,
        "nodatacow": nodatacow,
        "filesystem_compression": compressed,
        "advisories": advisories,
    }


def _tmpfs_capacity(path: Path) -> tuple[bool, int | None]:
    mount_point, filesystem = _mount_type(path)
    volatile = filesystem in {"tmpfs", "ramfs"}
    try:
        free = int(shutil.disk_usage(path).free)
    except OSError:
        free = None
    return bool(volatile), free


def resolve_dsm_placement(pgdata: Path, *, volatile_root: Path | None = None,
                          requested: str | None = None) -> dict[str, Any]:
    pgdata = Path(pgdata)
    requested = str(requested or "posix").strip().lower() or "posix"
    dynshmem = pgdata / "pg_dynshmem"
    shm = Path("/dev/shm")

    posix_ok = False
    posix_detail = "not evaluated"
    if requested == "posix":
        if not shm.is_dir():
            posix_detail = "/dev/shm is absent"
        else:
            volatile, free = _tmpfs_capacity(shm)
            if not volatile:
                posix_detail = "/dev/shm is not a tmpfs mount"
            elif free is not None and free < _MIN_POSIX_SHM_BYTES:
                posix_detail = (
                    f"/dev/shm has only {free // (1024 * 1024)} MiB free; "
                    "POSIX dynamic shared memory needs headroom for parallel-query bursts"
                )
            elif not os.access(shm, os.W_OK):
                posix_detail = "/dev/shm is not writable by this account"
            else:
                posix_ok = True
                posix_detail = "POSIX shared memory is RAM-backed and writes nothing to PGDATA"

    if posix_ok:
        return {
            "contract": FILESYSTEM_ENDURANCE_CONTRACT,
            "dynamic_shared_memory_type": "posix",
            "placement": "posix_shm",
            "volatile": True,
            "relocated_dynshmem": None,
            "detail": posix_detail,
            "advisories": [],
        }

    relocated = None
    if volatile_root is not None:
        candidate = Path(volatile_root) / "pg_dynshmem"
        volatile, _free = _tmpfs_capacity(Path(volatile_root))
        if volatile:
            candidate.mkdir(parents=True, exist_ok=True)
            relocated = candidate

    if relocated is not None:
        return {
            "contract": FILESYSTEM_ENDURANCE_CONTRACT,
            "dynamic_shared_memory_type": "mmap",
            "placement": "mmap_tmpfs",
            "volatile": True,
            "relocated_dynshmem": str(relocated),
            "detail": (
                f"POSIX dynamic shared memory unavailable ({posix_detail}); "
                f"pg_dynshmem redirected to tmpfs at {relocated}"
            ),
            "advisories": [],
        }

    return {
        "contract": FILESYSTEM_ENDURANCE_CONTRACT,
        "dynamic_shared_memory_type": "mmap",
        "placement": "mmap_pgdata",
        "volatile": False,
        "relocated_dynshmem": None,
        "detail": (
            f"POSIX dynamic shared memory unavailable ({posix_detail}) and no tmpfs was "
            f"available for {dynshmem}"
        ),
        "advisories": [
            "Dynamic shared memory is file-backed inside PGDATA. Every parallel query zero-fills "
            "a new segment on the data device. "
            "Make /dev/shm available, or mount a tmpfs and export GSD_VOLATILE_DIR."
        ],
    }
