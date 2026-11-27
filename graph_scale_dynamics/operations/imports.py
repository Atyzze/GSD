from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONTRACT = "gsd-imports-2"
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


DEX = "dex.json"


def is_bundle(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.is_file():
        return path.name.endswith(ARCHIVE_ENDINGS)
    return path.is_dir() and any((path / name).is_file() or len(list(path.glob(f"*/{name}"))) == 1
                                 for name in (STUDY, DEX))


def _stamp(path: Path) -> list:
    if path.is_file():
        st = path.stat()
        return [st.st_size, st.st_mtime_ns]
    inner = next((p for name in (STUDY, DEX) for p in [path / name, *path.glob(f"*/{name}")] if p.is_file()), path)
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
            "laws_only": len(bundle.get("laws_only") or []), "part": bundle.get("kind") or "study bundle",
            "regions": len(bundle["regions"]), "science": bundle["science"], "sha256": bundle["sha256"]}


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


def _in_map(record: dict | None) -> dict | None:
    if not record:
        return None
    from graph_scale_dynamics.operations import study_seed
    return {"at": record.get("at"), "laws_added": record.get("laws_added"), "regions": record.get("regions") or [],
            "selected": study_seed.selected(record), "let_go_utc": record.get("let_go_utc"),
            "laws_recorded": record.get("laws_recorded", record.get("laws") is not None),
            "laws_standing": record.get("laws_standing", len(record.get("laws") or {}))}


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
    from graph_scale_dynamics.operations import study_seed
    done = {str(r.get("bundle") or ""): r for r in study_seed.records({"seeded": seeded or []})}
    hashes = {str(r.get("sha256")): name for name, r in done.items() if r.get("sha256") and study_seed.selected(r)}
    entries = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if not is_bundle(path):
            continue
        stamp = _stamp(path)
        known = index.get(path.name)
        if not known or known.get("stamp") != stamp or (known["read"].get("readable")
                                                         and "sha256" not in known["read"]):
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
        twin = hashes.get(str(read.pop("sha256", None) or ""))
        entries.append(dict(read, name=path.name, kind="archive" if path.is_file() else "folder", bytes=_bytes(path),
                            seeded=_in_map(record), in_folder=True,
                            identical_to=twin if twin and twin != read.get("bundle") else None))
    listed = {str(e.get("bundle") or "") for e in entries}
    for name, record in done.items():
        if name not in listed:
            entries.append({"name": name, "bundle": name, "readable": True, "in_folder": False, "kind": "read",
                            "study": record.get("study"), "built_utc": record.get("built_utc"),
                            "scoring": record.get("scoring"), "science_same": True, "seeded": _in_map(record)})
    if changed or set(kept) != set(index):
        _save_index(var, kept)
    return {"contract": CONTRACT, "folder": str(folder), "exists": True, "bundles": entries,
            "reading": ("a dex or a study bundle put into this folder, its .tar.zst or its unpacked folder, is listed "
                        "here; a dex is read in by itself at the focus's next step, a study bundle once ticked and "
                        "synchronized; its laws, and its regions where it was read by this folder's science, are in "
                        "this study's map, a law of another science run here from nothing; synchronize reads in what "
                        "is newly ticked and lets go of what is unticked, the readings already taken kept; nothing in "
                        "the folder is changed or removed")}


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


def synchronize(repo, folder: Path | None, ticked, *, seeded: list | None = None) -> dict:
    from graph_scale_dynamics.operations import focus, study_seed
    wanted = {str(name or "") for name in ticked or []}
    wanted |= {study_seed.name_of(name) for name in wanted}
    state = focus.load(repo) if seeded is None else {"seeded": seeded}
    records = {str(r.get("bundle") or ""): r for r in study_seed.records(state)}
    paths: dict[str, Path] = {}
    if folder is not None and folder.is_dir():
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            if is_bundle(path):
                paths.setdefault(study_seed.name_of(path), path)
    read_in, let_go, refused, kept = [], [], [], []

    def attempt(name: str, act) -> None:
        try:
            act()
        except ValueError as exc:
            refused.append({"name": name, "why": str(exc)})

    for name, record in records.items():
        if name in wanted or not study_seed.selected(record):
            continue

        def release(name=name, record=record):
            if record.get("laws") is None and paths.get(name) is not None:
                study_seed.seed(repo, paths[name])
            let_go.append(study_seed.release(repo, name))
        attempt(name, release)
    for name in sorted(n for n in wanted if n in records or n in paths):
        record = records.get(name)
        if record is not None and study_seed.selected(record):
            if record.get("laws") is None and paths.get(name) is not None:
                attempt(name, lambda name=name: read_in.append(study_seed.seed(repo, paths[name])))
            else:
                kept.append(name)
        elif record is not None and record.get("laws") is not None:
            attempt(name, lambda name=name: read_in.append(study_seed.choose(repo, name)))
        elif paths.get(name) is not None:
            attempt(name, lambda name=name: read_in.append(study_seed.seed(repo, paths[name])))
        else:
            refused.append({"name": name, "why": f"{name} is not in the import folder"})
    return {"read_in": read_in, "let_go": let_go, "refused": refused, "kept": kept}


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


__all__ = ["CONTRACT", "FOLDER", "folder_of", "is_bundle", "listing", "named", "open_folder", "read_one", "seed",
           "synchronize"]
