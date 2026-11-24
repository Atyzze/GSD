from __future__ import annotations

import importlib
import platform
import pkgutil
from pathlib import Path

from graph_scale_dynamics.calibration import fingerprint as FP

GEOMETRY = "geometry"
GEOMETRY_CHANNELS = ("d_s", "d_V", "d_B", "d_w")
APPENDED_PACKAGE = "graph_scale_dynamics.probes"
APPENDED_DIR = "graph_scale_dynamics/probes"
GROUP_ATTRIBUTES = ("GROUP", "VERSION", "CHANNELS", "measure")


class ProbeGroupError(ValueError):
    pass


def geometry_fingerprint_of(analysis: str, estimator: str) -> str:
    return FP.short_hash(f"{analysis}|{estimator}")


def geometry_fingerprint(root=None) -> str:
    return geometry_fingerprint_of(FP.analysis_version(root), FP.estimator_fingerprint(root))


def appended_groups() -> dict:
    package = importlib.import_module(APPENDED_PACKAGE)
    out = {}
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        module = importlib.import_module(f"{APPENDED_PACKAGE}.{info.name}")
        missing = [name for name in GROUP_ATTRIBUTES if not hasattr(module, name)]
        if missing:
            raise ProbeGroupError(f"{module.__name__} is not a probe group: it has no {', '.join(missing)}")
        name = str(module.GROUP)
        if name == GEOMETRY or name in out:
            raise ProbeGroupError(f"two probe groups are named {name}")
        clash = set(module.CHANNELS) & set(GEOMETRY_CHANNELS)
        for other in out.values():
            clash |= set(module.CHANNELS) & set(other.CHANNELS)
        if clash:
            raise ProbeGroupError(f"{name} names channels another group owns: {', '.join(sorted(clash))}")
        out[name] = module
    return out


def group_module(group: str):
    groups = appended_groups()
    if group not in groups:
        raise ProbeGroupError(f"no appended probe group is named {group}; there are {', '.join(groups) or 'none'}")
    return groups[group]


def group_entry(group: str) -> str:
    return f"{APPENDED_DIR}/{group_module(group).__name__.rsplit('.', 1)[-1]}.py"


def group_fingerprint(group: str, root=None) -> str:
    if group == GEOMETRY:
        return geometry_fingerprint(root)
    module = group_module(group)
    return FP.short_hash("\n".join([str(module.VERSION), *FP.closure_digest(group_entry(group), root)]))


def channels_of(group: str) -> tuple[str, ...]:
    return GEOMETRY_CHANNELS if group == GEOMETRY else tuple(group_module(group).CHANNELS)


def current_fingerprints(root=None) -> dict[str, str]:
    return {GEOMETRY: geometry_fingerprint(root), **{g: group_fingerprint(g, root) for g in appended_groups()}}


def environment() -> dict:
    import numpy
    import scipy
    return {"python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__,
            "machine": platform.machine(), "system": platform.system()}


def root_of(root=None) -> Path:
    return Path(root) if root is not None else FP.repository_root()
