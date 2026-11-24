from __future__ import annotations

import math
from pathlib import Path


def _read_number(path: Path) -> float | None:
    try:
        value = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _btop_hwmon_temperature_sensors(hwmon_root: Path = Path("/sys/class/hwmon"),
                                    thermal_root: Path = Path("/sys/class/thermal")) -> list[dict]:
    search_paths: list[Path] = []
    seen_paths: set[str] = set()

    def add_search_path(path: Path) -> None:
        try:
            key = str(path.resolve())
            entries = list(path.iterdir())
        except OSError:
            return
        if key in seen_paths:
            return
        if any(item.name.startswith("temp") and item.name.endswith("_input") for item in entries):
            seen_paths.add(key)
            search_paths.append(path)

    try:
        hwmons = list(hwmon_root.iterdir())
    except OSError:
        hwmons = []
    for entry in hwmons:
        try:
            resolved = entry.resolve()
        except OSError:
            resolved = entry
        add_search_path(resolved / "device")
        add_search_path(resolved)

    records: list[dict] = []
    got_primary = False
    for base in search_paths:
        pname = _read_text(base / "name") or base.name
        try:
            files = list(base.iterdir())
        except OSError:
            continue
        for sensor in files:
            name = sensor.name
            if not (name.startswith("temp") and name.endswith("_input")):
                continue
            if "nvme" in str(sensor).lower():
                continue
            stem = name[:-6]
            label = _read_text(base / f"{stem}_label") or stem
            raw = _read_number(sensor)
            if raw is None:
                continue
            current = raw / 1000.0
            if not math.isfinite(current) or current < -20 or current > 150:
                continue
            sensor_name = f"{pname}/{label}"
            preferred = (label.startswith("Package id") or label.startswith("Tdie")
                         or label.startswith("SoC Temperature"))
            got_primary = got_primary or preferred
            records.append({
                "name": sensor_name,
                "group": pname,
                "label": label,
                "path": str(sensor),
                "temperature_celsius": current,
                "preferred": preferred,
            })

    if not got_primary:
        index = 0
        while True:
            zone = thermal_root / f"thermal_zone{index}"
            if not zone.exists():
                break
            raw = _read_number(zone / "temp")
            if raw is not None:
                current = raw / 1000.0
                if math.isfinite(current) and -20 <= current <= 150:
                    label = _read_text(zone / "type") or f"temp{index}"
                    records.append({
                        "name": f"thermal{index}/{label}",
                        "group": f"thermal{index}",
                        "label": label,
                        "path": str(zone / "temp"),
                        "temperature_celsius": current,
                        "preferred": False,
                    })
            index += 1
    return records


def _powercap_energy_zones(powercap_root: Path) -> list[Path]:
    try:
        roots = list(powercap_root.iterdir())
    except OSError:
        return []
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(zone: Path) -> None:
        if not (zone / "energy_uj").is_file():
            return
        try:
            key = str(zone.resolve())
        except OSError:
            key = str(zone)
        if key not in seen:
            seen.add(key)
            candidates.append(zone)

    for entry in roots:
        add(entry)
        try:
            if entry.is_dir():
                for child in entry.iterdir():
                    add(child)
        except OSError:
            continue
    return candidates


def _read_number_diagnostic(path: Path) -> tuple[float | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None, "not found"
    except PermissionError:
        return None, "permission denied"
    except OSError as exc:
        return None, f"{exc.__class__.__name__}: {exc}"
    try:
        value = float(raw)
    except ValueError:
        return None, "non-numeric value"
    if not math.isfinite(value):
        return None, "non-finite value"
    return value, None
