from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONTRACT = "gsd-imports-1"
FOLDER = "import"
INDEX = "import_index.json"
ARCHIVE_ENDINGS = (".tar.zst", "_tar.zst")
STUDY = "study.json"
_OURS: dict = {}


def folder_of(report_root) -> Path | None:
    if report_root is None:
        return None
    from graph_scale_dynamics.operations.report_home import base_of
    var = base_of(Path(report_root)).parent
    return var.parent / FOLDER


def _var_of(folder: Path) -> Path:
    return folder.parent / "var"


def is_bundle(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.is_file():
        return path.name.endswith(ARCHIVE_ENDINGS)
    return path.is_dir() and ((path / STUDY).is_file() or len(list(path.glob(f"*/{STUDY}"))) == 1)


def _stamp(path: Path) -> list:
    if path.is_file():
        st = path.stat()
        return [st.st_size, st.st_mtime_ns]
    inner = path / STUDY if (path / STUDY).is_file() else next(iter(path.glob(f"*/{STUDY}")), path)
    st = inner.stat()
    return [st.st_size, st.st_mtime_ns]


def _bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _ours() -> dict:
    if "science" not in _OURS:
        from graph_scale_dynamics.reporting import science_contract
        _OURS["science"] = science_contract.science()[0]
    return _OURS["science"]


def read_one(path: Path) -> dict:
    from graph_scale_dynamics.operations import study_seed
    try:
        bundle = study_seed.read(path)
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "why": f"{type(exc).__name__}: {exc}"[:300]}
    return {"readable": True, "bundle": bundle["name"], "study": bundle["study"], "built_utc": bundle["built_utc"],
            "build": bundle.get("build"), "laws": len(bundle["specs"]), "scoring": len(bundle["scoring"]),
            "regions": len(bundle["regions"]), "science": bundle["science"]}


def _index(var: Path) -> dict:
    try:
        found = json.loads((var / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _save_index(var: Path, index: dict) -> None:
    try:
        var.mkdir(parents=True, exist_ok=True)
        part = var / (INDEX + ".part")
        part.write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
        os.replace(part, var / INDEX)
    except OSError:
        return


def listing(folder: Path | None, *, seeded: list | None = None, ours: dict | None = None,
            reader=read_one) -> dict:
    if folder is None:
        return {"contract": CONTRACT, "folder": None, "exists": False, "bundles": [],
                "why": "this runtime has no folder of its own, so no import folder"}
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"contract": CONTRACT, "folder": str(folder), "exists": False, "bundles": [],
                "why": f"{type(exc).__name__}: {exc}"}
    var = _var_of(folder)
    index, kept, changed = _index(var), {}, False
    done = {}
    for record in seeded or []:
        done[str(record.get("bundle") or "")] = record
    entries = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if not is_bundle(path):
            continue
        stamp = _stamp(path)
        known = index.get(path.name)
        if not known or known.get("stamp") != stamp:
            known = {"stamp": stamp, "read": reader(path)}
            changed = True
        kept[path.name] = known
        read = dict(known["read"])
        science = read.pop("science", None)
        if read.get("readable"):
            from graph_scale_dynamics.reporting import science_contract
            compared = science_contract.same(science, ours if ours is not None else _ours())
            read["science_same"], read["science_differ"] = compared["same"], compared["differ"]
        record = done.get(str(read.get("bundle") or ""))
        entries.append(dict(read, name=path.name, kind="archive" if path.is_file() else "folder", bytes=_bytes(path),
                            seeded=({"at": record.get("at"), "laws_added": record.get("laws_added"),
                                     "regions": record.get("regions") or []} if record else None)))
    if changed or set(kept) != set(index):
        _save_index(var, kept)
    return {"contract": CONTRACT, "folder": str(folder), "exists": True, "bundles": entries,
            "reading": ("a study bundle put into this folder, its .tar.zst or its unpacked folder, is listed here and can "
                        "be ticked to seed the study; nothing in the folder is changed or removed")}


def named(folder: Path | None, names) -> list[Path]:
    if folder is None:
        raise ValueError("this runtime has no folder of its own, so no import folder")
    picked = []
    for name in names or []:
        name = str(name or "")
        path = folder / name
        if not name or Path(name).name != name or not path.exists() or not is_bundle(path):
            raise ValueError(f"no study bundle named {name!r} in {folder}")
        picked.append(path)
    if not picked:
        raise ValueError("tick at least one bundle to seed from")
    return picked


def seed(repo, folder: Path | None, names) -> dict:
    from graph_scale_dynamics.operations import study_seed
    seeded, failed = [], []
    for path in named(folder, names):
        try:
            seeded.append(study_seed.seed(repo, path))
        except ValueError as exc:
            failed.append({"name": path.name, "why": str(exc)})
    if failed and not seeded:
        raise ValueError("; ".join(f"{f['name']}: {f['why']}" for f in failed))
    return {"seeded": seeded, "failed": failed}


def opener() -> list[str] | None:
    if sys.platform.startswith("win"):
        return ["explorer"]
    found = shutil.which("open" if sys.platform == "darwin" else "xdg-open")
    return [found] if found else None


def open_folder(folder: Path | None, *, launch=None) -> dict:
    if folder is None:
        raise ValueError("this runtime has no folder of its own, so no import folder")
    folder.mkdir(parents=True, exist_ok=True)
    command = opener()
    if command is None:
        raise ValueError(f"no file manager to open on this host: the import folder is {folder}")
    run = launch or (lambda argv: subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                   stderr=subprocess.DEVNULL, start_new_session=True))
    run([*command, str(folder)])
    return {"opened": str(folder)}


__all__ = ["CONTRACT", "FOLDER", "folder_of", "is_bundle", "listing", "named", "open_folder", "read_one", "seed"]
