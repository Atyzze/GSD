from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from graph_scale_dynamics.calibration import admission as A

GIB = 1024 ** 3
_hook = None

CURVES: dict[str, list[float]] = {
    "periodic_ring": [0.03, 0.16, 0.16, 0.16, 0.21, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33,
                      0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0.17, 0.17, 0.17,
                      0.22, 0.32, 0.4, 0.5, 0.58, 0.68, 0.75, 0.85, 0.91, 0.99, 1.0, 0.36, 0.33],
    "periodic_square_lattice": [0.03, 0.17, 0.16, 0.16, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32, 0.32,
                                0.32, 0.32, 0.32, 0.32, 0.31, 0.31, 0.21, 0.21, 0.21, 0.21, 0.21, 0.21, 0.21,
                                0.21, 0.21, 0.21, 0.47, 0.78, 0.9, 1.0, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96,
                                0.96, 0.96],
    "periodic_triangular_lattice": [0.14, 0.18, 0.17, 0.26, 0.36, 0.36, 0.36, 0.36, 0.36, 0.36, 0.36, 0.36,
                                    0.36, 0.36, 0.36, 0.36, 0.18, 0.18, 0.18, 0.18, 0.18, 0.18, 0.18, 0.18,
                                    0.18, 0.22, 0.74, 0.88, 0.98, 1.0, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96,
                                    0.96, 0.96, 0.96, 0.96, 0.34],
    "periodic_honeycomb_lattice": [0.14, 0.2, 0.2, 0.2, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42,
                                   0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.38, 0.38, 0.24, 0.24,
                                   0.24, 0.24, 0.24, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.82,
                                   0.97, 1.0, 0.94, 0.45],
    "erdos_renyi_sparse": [0.42, 0.46, 0.46, 0.46, 0.46, 0.68, 0.83, 0.83, 0.83, 0.83, 0.83, 0.83, 0.83, 0.83,
                           0.83, 0.83, 0.83, 0.83, 0.74, 0.74, 0.52, 0.52, 0.53, 0.52, 0.52, 0.53, 0.52, 0.53,
                           0.53, 0.53, 0.53, 0.52, 0.52, 0.52, 0.52, 0.52, 0.52, 1.0, 1.0, 1.0, 0.84],
    "random_3_regular": [0.33, 0.45, 0.45, 0.45, 0.45, 0.45, 0.84, 0.84, 0.84, 0.84, 0.84, 0.84, 0.84, 0.84,
                         0.84, 0.84, 0.84, 0.84, 0.78, 0.78, 0.48, 0.48, 0.5, 0.5, 0.49, 0.49, 0.49, 0.49,
                         0.49, 0.86, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    "random_4_regular": [0.31, 0.34, 0.45, 0.46, 0.46, 0.46, 0.46, 0.66, 0.88, 0.88, 0.88, 0.88, 0.88, 0.88,
                         0.88, 0.88, 0.88, 0.88, 0.88, 0.75, 0.75, 0.45, 0.5, 0.5, 0.49, 0.49, 0.49, 0.49,
                         0.49, 0.88, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    "uniform_random_tree": [0.28, 0.49, 0.47, 0.47, 0.61, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99,
                            0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.53, 0.53, 0.53, 0.53,
                            0.53, 0.53, 0.53, 0.53, 0.54, 0.54, 0.54, 0.54, 0.54, 0.54, 0.54, 1.0, 0.96],
}


@dataclass
class SimCell:
    key: str
    family: str
    peak: int
    price: int
    work: float
    typical_share: float = A.TYPICAL_SHARE
    done: float = 0.0
    started: float | None = None
    paused_at: float | None = None
    paused_seconds: float = 0.0
    strict: bool = False
    sheds: int = 0
    samples: deque = field(default_factory=deque)

    def held(self) -> int:
        if self.started is None:
            return 0
        curve = CURVES[self.family]
        x = min(1.0, self.done / self.work) * (len(curve) - 1)
        i = min(len(curve) - 2, int(x))
        share = curve[i] + (curve[i + 1] - curve[i]) * (x - i)
        return int(self.peak * share)

    def view(self, now: float) -> A.CellMemory:
        held = self.held()
        window = [v for t, v in self.samples if now - t <= A.GROWTH_WINDOW_SECONDS]
        growth = held - min(window) if window else 0
        return A.CellMemory(key=self.key, started=float(self.started if self.started is not None else now),
                            price=self.price, typical=int(self.price * self.typical_share), held=held,
                            growth=growth, paused=self.paused_at is not None, paused_at=self.paused_at,
                            strict=self.strict)


def simulate(cells: list[SimCell], *, rule: str, available: int, floor: int = 10 * GIB, workers: int = 31,
             cores: int = 16, tick: float = 1.0, patience: float = 1200.0, limit: float = 48 * 3600) -> dict:
    pending = list(cells)
    running: list[SimCell] = []
    paused: list[SimCell] = []
    finished: list[SimCell] = []
    blocked: list[SimCell] = []
    now = 0.0
    lowest = available
    counts = {"paused": 0, "continued": 0, "ended": 0}
    area_running = area_held = 0.0
    most = 0
    head_since: dict[str, float] = {}

    def free() -> int:
        return available - sum(c.held() for c in running + paused)

    def end(cell: SimCell) -> None:
        (paused if cell in paused else running).remove(cell)
        cell.done, cell.started, cell.paused_at = 0.0, None, None
        cell.samples.clear()
        cell.sheds += 1
        counts["ended"] += 1
        if rule == "526" and cell.sheds >= 2:
            blocked.append(cell)
        else:
            cell.strict = True
            pending.insert(0, cell)

    while (pending or running or paused) and now < limit:
        for cell in [c for c in running if c.done >= c.work]:
            running.remove(cell)
            finished.append(cell)
            peak = max(c.peak for c in finished if c.family == cell.family)
            for other in (pending if rule == "526" else pending + running + paused):
                if other.family == cell.family:
                    other.price = int((A.MEASURED_MARGIN if rule == "526" else A.SAME_SIZE_MARGIN) * peak)
        mem = free()
        lowest = min(lowest, mem)
        if rule == "526":
            if running and mem < A.shed_line(floor):
                end(max(running, key=lambda c: c.started))
                continue
        else:
            views = {id(c): c.view(now) for c in running + paused}
            asked = A.pressure([views[id(c)] for c in running], [views[id(c)] for c in paused], mem, floor)
            if asked and asked[0][0] == "end":
                end(next(c for c in running + paused if c.key == asked[0][1].key))
                continue
            for _action, view in asked:
                cell = next(c for c in running if c.key == view.key)
                running.remove(cell)
                cell.paused_at = now
                paused.append(cell)
                counts["paused"] += 1
            if asked:
                views = {id(c): c.view(now) for c in running + paused}
            view = A.to_continue([views[id(c)] for c in running], [views[id(c)] for c in paused], mem, floor, now)
            if view is not None:
                cell = next(c for c in paused if c.key == view.key)
                paused.remove(cell)
                cell.paused_seconds += now - (cell.paused_at or now)
                cell.paused_at = None
                running.append(cell)
                counts["continued"] += 1
        started_one = True
        while started_one and pending and len(running) + len(paused) < workers and not paused:
            started_one = False
            for index, cell in enumerate(list(pending)):
                budget = free() - floor
                if rule == "526":
                    need = cell.price + sum(A.remaining_bytes(c.price, c.held()) for c in running)
                    fits = need <= budget
                else:
                    candidate = A.CellMemory(key=cell.key, started=now, price=cell.price,
                                             typical=int(cell.price * cell.typical_share), strict=cell.strict)
                    fits, _need = A.fits_beside(candidate, [c.view(now) for c in running], budget)
                if fits:
                    pending.remove(cell)
                    cell.started = now
                    running.append(cell)
                    head_since.pop(cell.key, None)
                    started_one = True
                    break
                if index == 0:
                    since = head_since.setdefault(cell.key, now)
                    if running and now - since >= patience:
                        break
        if not running and not paused and pending:
            head = pending[0]
            pending.remove(head)
            head.started = now
            running.append(head)
        speed = 1.0 if len(running) <= cores else (cores + 0.25 * (min(len(running), 2 * cores) - cores)) / len(running)
        for cell in running:
            cell.done += speed * tick
        for cell in running + paused:
            cell.samples.append((now, cell.held()))
            while cell.samples and now - cell.samples[0][0] > A.GROWTH_WINDOW_SECONDS:
                cell.samples.popleft()
        if _hook is not None:
            _hook(now, running, paused)
        most = max(most, len(running))
        area_running += len(running) * tick
        area_held += sum(c.held() for c in running + paused) * tick
        now += tick
    return {"hours": round(now / 3600, 2), "finished": len(finished), "blocked": len(blocked),
            "mean_running": round(area_running / max(now, tick), 1), "most_running": most,
            "mean_held_gib": round(area_held / max(now, tick) / GIB, 1),
            "lowest_available_gib": round(lowest / GIB, 1), **counts,
            "paused_cell_hours": round(sum(c.paused_seconds for c in finished) / 3600, 2)}


def operators_21(*, peaks: dict | None = None, prices: dict | None = None) -> list[SimCell]:
    g = GIB
    peaks = dict({"erdos_renyi_sparse": 4.4 * g, "periodic_honeycomb_lattice": 3.76 * g, "periodic_ring": 11.5 * g,
                  "periodic_square_lattice": 15.3 * g, "periodic_triangular_lattice": 16.8 * g,
                  "random_3_regular": 4.9 * g, "random_4_regular": 6.05 * g, "uniform_random_tree": 4.1 * g},
                 **(peaks or {}))
    model = A.predicted_cell_bytes(4_194_304)
    prices = dict({"erdos_renyi_sparse": 1.25 * peaks["erdos_renyi_sparse"],
                   "periodic_honeycomb_lattice": 1.10 * peaks["periodic_honeycomb_lattice"],
                   "periodic_ring": 1.10 * peaks["periodic_ring"],
                   "periodic_square_lattice": model, "periodic_triangular_lattice": model,
                   "random_3_regular": 1.25 * peaks["random_3_regular"],
                   "random_4_regular": 1.25 * peaks["random_4_regular"],
                   "uniform_random_tree": 1.25 * peaks["uniform_random_tree"]}, **(prices or {}))
    seconds = {"erdos_renyi_sparse": 182, "periodic_honeycomb_lattice": 124, "periodic_ring": 104,
               "periodic_square_lattice": 168, "periodic_triangular_lattice": 214, "random_3_regular": 222,
               "random_4_regular": 272, "uniform_random_tree": 121}
    seeds = {"erdos_renyi_sparse": (0, 1, 2), "periodic_honeycomb_lattice": (2,), "periodic_ring": (1, 2),
             "periodic_square_lattice": (0, 1, 2), "periodic_triangular_lattice": (0, 1, 2),
             "random_3_regular": (0, 1, 2), "random_4_regular": (0, 1, 2), "uniform_random_tree": (0, 1, 2)}
    return [SimCell(key=f"{family}:4M:{seed}", family=family, peak=int(peaks[family]), price=int(prices[family]),
                    work=seconds[family] * 19.6 * (1 + 0.03 * seed))
            for family in sorted(seeds) for seed in seeds[family]]
