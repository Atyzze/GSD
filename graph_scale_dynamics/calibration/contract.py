from __future__ import annotations

import os
from pathlib import Path

CONTRACT = "gsd-calibration-table-1"

SUITE_VERSION = 3

AUTHORITATIVE_SEEDS = 10

SUITE_FAMILIES: tuple[str, ...] = (
    "periodic_ring",
    "periodic_square_lattice",
    "periodic_triangular_lattice",
    "periodic_honeycomb_lattice",
    "periodic_cubic_lattice",
    "periodic_hypercubic_lattice_4d",
    "sierpinski_gasket",
    "sierpinski_carpet",
    "uniform_random_tree",
    "balanced_binary_tree",
    "random_3_regular",
    "random_4_regular",
    "erdos_renyi_sparse",
    "erdos_renyi_mid",
    "erdos_renyi_dense",
    "erdos_renyi_degree_2",
    "erdos_renyi_degree_6",
    "periodic_cubic_quotient",
    "periodic_body_centred_cubic_lattice",
    "periodic_face_centred_cubic_lattice",
    "periodic_tesseract_quotient",
    "hyperbolic_triangle_tiling",
    "hyperbolic_geometric_graph",
    "periodic_a4_lattice",
    "periodic_d4_lattice",
    "erdos_renyi_degree_16",
    "erdos_renyi_degree_32",
)

MAX_NODES = 1_048_576

_TO_1M = (1048576,)
LADDER_EXTENSIONS: dict[str, tuple] = {
    "uniform_random_tree": _TO_1M,
    "balanced_binary_tree": (19,),
    "random_3_regular": _TO_1M,
    "erdos_renyi_sparse": _TO_1M,
    "erdos_renyi_mid": _TO_1M,
    "erdos_renyi_dense": _TO_1M,
    "erdos_renyi_degree_2": _TO_1M,
    "erdos_renyi_degree_6": _TO_1M,
}
EXTENSION_SEEDS = 3

CHANNELS: tuple[str, ...] = ("d_s", "d_B", "d_w", "d_V")

CHANNEL_VALUE_KEYS: dict[str, str] = {"d_s": "d_s", "d_B": "d_B", "d_w": "d_w", "d_V": "d_V_window"}

DURABLE_DIR = "calibration"
DURABLE_NAME = "probe_calibration.json"

WORKING_DIR = "calibration"
NON_AUTHORITATIVE_NAME = "probe_calibration.json"
HISTORY_DIR = "history"
WAIVERS_NAME = "waivers.json"

ENV_DEV_MODE = "GSD_DEV_MODE"
ENV_PROFILE = "GSD_CALIBRATION_PROFILE"
ENV_REDUCED_SEEDS = "GSD_CALIBRATION_REDUCED_SEEDS"
ENV_REDUCED_MAX_NODES = "GSD_CALIBRATION_REDUCED_MAX_NODES"
ENV_WORKERS = "GSD_CALIBRATION_WORKERS"
ENV_INTEGRATION_TEST = "GSD_INTEGRATION_TEST"

REDUCED_SEEDS_DEFAULT = 2
REDUCED_MAX_NODES_DEFAULT = 1100

PROFILE_FULL = "full"
PROFILE_REDUCED = "reduced"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def durable_artifact_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else repository_root()) / DURABLE_DIR / DURABLE_NAME


SEED_TABLE_NAME = "seed_table.json"


def candidate_table_paths(root: Path | None = None) -> list[Path]:
    here = (Path(root) if root is not None else repository_root()).resolve()
    return [here / DURABLE_DIR / SEED_TABLE_NAME]


def working_dir(var: Path) -> Path:
    return Path(var) / WORKING_DIR


def non_authoritative_artifact_path(var: Path) -> Path:
    return working_dir(var) / NON_AUTHORITATIVE_NAME


def history_dir(var: Path) -> Path:
    return working_dir(var) / HISTORY_DIR


def waivers_path(var: Path) -> Path:
    return working_dir(var) / WAIVERS_NAME


def dev_mode() -> bool:
    from graph_scale_dynamics.operations.dev_mode import enabled
    return enabled()


def profile() -> str:
    explicit = (os.environ.get(ENV_PROFILE) or "").strip().lower()
    if explicit in (PROFILE_FULL, PROFILE_REDUCED):
        return explicit
    if os.environ.get(ENV_INTEGRATION_TEST) == "1":
        return PROFILE_REDUCED
    return PROFILE_FULL


def reduced_seeds() -> int:
    return max(1, int(os.environ.get(ENV_REDUCED_SEEDS) or REDUCED_SEEDS_DEFAULT))


def reduced_max_nodes() -> int:
    return max(16, int(os.environ.get(ENV_REDUCED_MAX_NODES) or REDUCED_MAX_NODES_DEFAULT))
