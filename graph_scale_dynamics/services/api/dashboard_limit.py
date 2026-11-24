from __future__ import annotations

from graph_scale_dynamics.observability import dashboard_timing

SLOT_WAIT_SECONDS = 2.0
BUSY = {"error": "dashboard database capacity busy", "retryable": True}

LIMITED_ROUTES = (
    ("api", "structure"), ("api", "gate"), ("api", "performance"), ("api", "memory-ledger"), ("api", "stranded"),
    ("api", "schema"), ("api", "calibration"), ("api", "supervisor-log"), ("api", "runtime-imports"),
    ("api", "reports", "status"),
)


def limited(parts: list[str]) -> bool:
    return any(tuple(parts[:len(route)]) == route for route in LIMITED_ROUTES)


def within(handler, slots, answer, route: str):
    clock = dashboard_timing.RequestClock(route)
    if not slots.acquire(timeout=SLOT_WAIT_SECONDS):
        clock.mark("slot_wait")
        clock.finish("capacity_busy")
        return handler._json(dict(BUSY), 503)
    clock.mark("slot_wait")
    try:
        return answer()
    finally:
        slots.release()
        clock.finish()


def serve(handler, slots, get):
    route = handler._route_path()
    if not limited([part for part in route.split("/") if part]):
        return get()
    return within(handler, slots, get, route)
