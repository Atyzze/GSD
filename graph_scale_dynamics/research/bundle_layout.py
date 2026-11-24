from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path

MAX_UNPACKED_BYTES = 64 * 2**30


def extract(archive: Path, target: Path, *, max_bytes: int = MAX_UNPACKED_BYTES) -> Path:
    archive, target = Path(archive), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    proc = None
    if archive.name.endswith(".zst"):
        proc = subprocess.Popen([shutil.which("zstd") or "zstd", "-dc", str(archive)], stdout=subprocess.PIPE)
        tar = tarfile.open(fileobj=proc.stdout, mode="r|")
    else:
        tar = tarfile.open(archive, mode="r:*")
    total, clean = 0, False
    try:
        for member in tar:
            total += max(0, int(member.size))
            if total > max_bytes:
                raise ValueError(f"{archive.name} unpacks to more than {max_bytes:,} bytes; refused")
            tar.extract(member, target, filter="data")
        clean = True
    finally:
        tar.close()
        if proc is not None:
            proc.stdout.close()
            if not clean:
                proc.kill()
            if proc.wait() != 0 and clean:
                raise RuntimeError(f"zstd could not decompress {archive}")
    return target


def report_path(bundle: Path, name: str) -> Path:
    bundle = Path(bundle)
    code = name.split("-", 1)[0].replace(".json", "").zfill(2)
    flat = bundle / (name if name.endswith(".json") else f"{name}.json")
    if flat.exists():
        return flat
    for candidate in sorted(bundle.glob(f"{code}-*.json")):
        return candidate
    nested = bundle / "reports" / f"{code}.json"
    if nested.exists():
        return nested
    raise FileNotFoundError(
        f"report {code} not found in {bundle}: neither {code}-<slug>.json (dashboard bundle) "
        f"nor reports/{code}.json (report-export) is present")


def read_report(bundle: Path, name: str) -> dict:
    return json.loads(report_path(bundle, name).read_text())
