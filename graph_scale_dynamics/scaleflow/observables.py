from __future__ import annotations

OBSERVABLE_VOCABULARY_CONTRACT = "gsd-observables-1"

SPECTRAL_DIMENSION = "spectral_dimension_estimate"
DISTANCE_VOLUME_EXPONENT = "distance_volume_exponent"
BOX_COVERING_EXPONENT = "box_covering_exponent"
WALK_DIMENSION = "walk_dimension"

OBSERVABLE_ALIASES: dict[str, str] = {
    SPECTRAL_DIMENSION: "d_s",
    DISTANCE_VOLUME_EXPONENT: "d_V",
    BOX_COVERING_EXPONENT: "d_B",
    WALK_DIMENSION: "d_w",
}

CANONICAL_BY_ALIAS: dict[str, str] = {
    alias: canonical for canonical, alias in OBSERVABLE_ALIASES.items()
}

OBSERVABLE_DESCRIPTIONS: dict[str, str] = {
    SPECTRAL_DIMENSION: "finite-size spectral-dimension estimate",
    DISTANCE_VOLUME_EXPONENT: "finite-size distance-volume growth exponent",
    BOX_COVERING_EXPONENT: "finite-size box-covering (Minkowski) exponent",
    WALK_DIMENSION: "finite-size random-walk (transport) exponent",
}

DIMENSION_LIKE_OBSERVABLES: tuple[str, ...] = (
    SPECTRAL_DIMENSION,
    DISTANCE_VOLUME_EXPONENT,
    BOX_COVERING_EXPONENT,
)

NO_CHANNEL_MEASURES_HAUSDORFF_DIMENSION = (
    "Hausdorff dimension requires a diameter-to-zero limit that a finite graph "
    "does not have. d_s, d_V, and d_B are finite-size exponents whose "
    "agreement or disagreement is the evidence; none is a Hausdorff dimension."
)

MEAN_DEGREE = "mean_degree"
CONNECTED_FRACTION = "connected_fraction"
TWO_CORE_FRACTION = "two_core_fraction"
CYCLE_DENSITY = "cycle_density"
CLUSTERING = "clustering"
DEGREE_HETEROGENEITY = "degree_heterogeneity"

STRUCTURAL_OBSERVABLES: tuple[str, ...] = (
    MEAN_DEGREE,
    CONNECTED_FRACTION,
    TWO_CORE_FRACTION,
    CYCLE_DENSITY,
    CLUSTERING,
    DEGREE_HETEROGENEITY,
)

STATE_VECTOR_OBSERVABLES: tuple[str, ...] = (
    DIMENSION_LIKE_OBSERVABLES + STRUCTURAL_OBSERVABLES
)

IMPLAUSIBLE_ABOVE: dict[str, float] = {
    "d_s": 24.0,
    "d_V": 24.0,
    "d_B": 24.0,
    "d_w": 24.0,
}


def alias(canonical: str) -> str:
    return OBSERVABLE_ALIASES.get(canonical, canonical)


def canonical(name: str) -> str:
    return CANONICAL_BY_ALIAS.get(name, name)


def describe(canonical_name: str) -> str:
    return OBSERVABLE_DESCRIPTIONS.get(canonical_name, canonical_name)
