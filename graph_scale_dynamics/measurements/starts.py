from __future__ import annotations

from dataclasses import dataclass

from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements import random_starts

EMPTY, RANDOM, LATTICE = "empty", "random", "lattice"


@dataclass(frozen=True)
class Start:
    name: str
    kind: str
    family: str | None = None
    dimension: int | None = None
    neighbours: int | None = None
    runs: bool = True

    def reaches(self, n: int) -> bool:
        from graph_scale_dynamics.measurements.calibration import control_family_reaches
        if self.kind != LATTICE:
            raise ValueError(f"the {self.name} start is not built from its size alone")
        return control_family_reaches(str(self.family), int(n))

    def edges(self, n: int) -> list[tuple[int, int]] | None:
        from graph_scale_dynamics.measurements.calibration import control_family_edges
        if self.kind != LATTICE:
            raise ValueError(f"the {self.name} start is not built from its size alone")
        return control_family_edges(str(self.family), int(n))

    def declared(self) -> dict:
        if self.kind == EMPTY:
            raise ValueError("the chain from empty is every law's and is not declared")
        return {"name": self.name, "family": str(self.family)}


STARTS = (
    Start("empty", EMPTY),
    Start("random", RANDOM, random_starts.DRAWN),
    Start("honeycomb", LATTICE, K.HONEYCOMB_TORUS, 2, 3, runs=False),
    Start("square", LATTICE, K.SQUARE_TORUS, 2, 4),
    Start("triangular", LATTICE, K.TRIANGULAR_TORUS, 2, 6),
    Start("cubic", LATTICE, K.CUBIC_QUOTIENT, 3, 6),
    Start("bcc", LATTICE, K.BODY_CENTRED_CUBIC, 3, 8),
    Start("fcc", LATTICE, K.FACE_CENTRED_CUBIC, 3, 12),
    Start("tesseract", LATTICE, K.TESSERACT_QUOTIENT, 4, 8),
)
BY_NAME = {start.name: start for start in STARTS}
BY_FAMILY = {start.family: start for start in STARTS if start.family is not None}


def known_lattices() -> tuple[Start, ...]:
    return tuple(start for start in STARTS if start.kind == LATTICE)


def run() -> tuple[Start, ...]:
    return tuple(start for start in STARTS if start.runs)


def the_twin_starts() -> tuple[Start, ...]:
    return tuple(start for start in STARTS if start.kind in (EMPTY, RANDOM))


def lattices_run() -> tuple[Start, ...]:
    return tuple(start for start in run() if start.kind == LATTICE)


def declared() -> list[dict]:
    return [start.declared() for start in run() if start.kind != EMPTY]


def named(name: str) -> Start | None:
    return BY_NAME.get(str(name))


def of_family(family) -> Start | None:
    return BY_FAMILY.get(family)
