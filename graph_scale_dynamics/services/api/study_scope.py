from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

from graph_scale_dynamics.services.api import admin_view, freshness
from graph_scale_dynamics.services.api.law_order import LATTICE_WHO, law_rank

STUDY = "study"
CONTRACT = "gsd-study-scope-1"
TOP = 100
_LADDER_ADDS = ("abandoned", "analysing", "attempts", "chains", "completed", "done_without_artifact", "graphs",
                "interrupted", "budget_ended_seeds", "budget_ended_laws", "running_laws", "queued_laws",
                "analysing_laws", "queued_analyses_laws",
                "interrupted_seconds", "kappa_timed_measurements", "laws", "measured", "memory_timed_attempts",
                "probe_timed_measurements", "queued", "queued_analyses", "running", "running_seconds", "simulations",
                "stopped", "left", "still_here", "done", "d_s_ran", "d_V_ran", "d_B_ran", "d_w_ran",
                "d_s_timed", "d_V_timed", "d_B_timed", "d_w_timed")
_LADDER_COUNTS_BY_RULE = ("stopped_by_rule", "left_by_rule", "parked_by_rule", "done_by_rule")
_LADDER_MAX = ("max_seconds", "work_budget", "budget_seconds", "fallback_reservation_bytes", "peak_bytes_max",
               "longest_unfinished_seconds")
_LADDER_MIN = ("min_seconds", "peak_bytes_min")


def _add(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + b
    if isinstance(a, dict) and isinstance(b, dict):
        return {key: (_add(a[key], b[key]) if key in a and key in b else a.get(key, b.get(key)))
                for key in {**a, **b}}
    return a if a is not None else b


LATTICE_KINDS = LATTICE_WHO


def _scored_at(point: dict, name: str) -> bool:
    found = point.get("law_score") or {}
    return found.get("by") in LATTICE_KINDS and found.get("chain") == name


def merge_every_chain(bodies: list[dict]) -> dict:
    names, points, counts, contract = [], {}, {}, None
    for body in bodies:
        every, cid = body.get("every_chain") or {}, str(body.get("campaign_id"))
        contract = contract or every.get("contract")
        names.extend(name for name in every.get("names") or [] if name not in names)
        for name, drawn in (every.get("points") or {}).items():
            points.setdefault(name, []).extend(dict(point, campaign_id=point.get("campaign_id") or cid)
                                               for point in drawn or [] if _scored_at(point, name))
        for name, counted in (every.get("counts") or {}).items():
            counts[name] = _add(counts[name], counted or {}) if name in counts else dict(counted or {})
    return {"contract": contract, "names": names, "points": points, "counts": counts}


def merge_landscapes(bodies: list[dict]) -> dict:
    if not bodies:
        return {"campaign_id": STUDY, "contract": CONTRACT, "batches": [], "dimension_points": [], "counts": {},
                "top_candidates": []}
    points, top, counts, exposure = [], [], {}, {}
    for body in bodies:
        cid = str(body.get("campaign_id"))
        points.extend(dict(point, campaign_id=point.get("campaign_id") or cid) for point in body.get("dimension_points") or [])
        top.extend(dict(row, campaign_id=row.get("campaign_id") or cid) for row in body.get("top_candidates") or [])
        counts = _add(counts, body.get("counts") or {}) if counts else dict(body.get("counts") or {})
        exposure = _add(exposure, body.get("exposure") or {}) if exposure else dict(body.get("exposure") or {})
    first = bodies[0]
    batches = [str(b.get("campaign_id")) for b in bodies]
    selection = dict(first.get("selection") or {})
    selection["headline"] = f"all {len(batches)} batches: campaigns {', '.join(batches)}"
    ledgers = [b["gates_ledger"] for b in bodies if isinstance(b.get("gates_ledger"), dict)]
    return {**{key: first.get(key) for key in ("analysis_version", "limits", "score_model")},
            "campaign_id": STUDY, "contract": CONTRACT, "batches": batches,
            "revision": revision_of([b.get("revision") for b in bodies]),
            "generated_utc": max(str(b.get("generated_utc") or "") for b in bodies),
            "counts": counts, "exposure": exposure, "dimension_points": points, "refused_candidates": [],
            "selection": selection, "top_candidates": sorted(top, key=law_rank)[:TOP],
            "lattice_who": list(LATTICE_WHO), "gates_ledger": merge_ledgers(ledgers),
            "every_chain": merge_every_chain(bodies)}


def merge_ledgers(ledgers: list[dict]) -> dict | None:
    if not ledgers:
        return None
    import copy
    merged = copy.deepcopy(max(ledgers, key=lambda g: int(g.get("decisions_read") or 0)))
    if not any("scored_from" in g for g in ledgers):
        return merged
    for gate, by_size in (merged.get("gates") or {}).items():
        for n, entry in by_size.items():
            theirs = [((g.get("gates") or {}).get(gate) or {}).get(n) or {} for g in ledgers]
            entry["scored"] = sum(int(e.get("scored") or 0) for e in theirs)
            best = max((e for e in theirs if e.get("best_score") is not None), key=lambda e: e["best_score"],
                       default=None)
            entry["best_score"], entry["best_law"] = (best["best_score"], best.get("best_law")) if best else (None, None)
    merged["scored_from"] = sorted({c for g in ledgers for c in g.get("scored_from") or []})
    merged["scored_at_least"] = any(g.get("scored_at_least") for g in ledgers)
    return merged


def revision_of(revisions: list) -> str:
    return hashlib.sha256("|".join(str(r) for r in revisions).encode("utf-8")).hexdigest()[:20]


def merge_ladder(ladders: list[list[dict]]) -> list[dict]:
    by_n: dict = {}
    for rows in ladders:
        for row in rows or []:
            by_n.setdefault(int(row.get("n") or 0), []).append(row)
    out = []
    for n in sorted(by_n):
        rows = by_n[n]
        merged = {"n": n}
        weights = [max(0, int(r.get("completed") or 0)) for r in rows]
        for key in {k for r in rows for k in r} - {"n"}:
            values = [r.get(key) for r in rows]
            numbers = [(v, w) for v, w in zip(values, weights, strict=True)
                       if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if key in _LADDER_ADDS or key.endswith("_total"):
                merged[key] = sum(v for v, _w in numbers) if numbers else None
            elif key in _LADDER_MAX:
                merged[key] = max((v for v, _w in numbers), default=None)
            elif key in _LADDER_MIN:
                merged[key] = min((v for v, _w in numbers), default=None)
            elif key == "max_unfinished":
                merged[key] = _the_longest_is_unfinished(rows)
            elif key in _LADDER_COUNTS_BY_RULE:
                total: dict = {}
                for value in values:
                    total = _add(total, value or {}) if total else dict(value or {})
                merged[key] = total
            elif numbers:
                weight = sum(w for _v, w in numbers)
                merged[key] = (sum(v * w for v, w in numbers) / weight) if weight else numbers[0][0]
            else:
                merged[key] = next((v for v in values if v is not None), None)
        out.append(merged)
    whole = sum(float(r.get("rung_seconds_total") or 0.0) for r in out)
    for row in out:
        if "compute_share" in row:
            row["compute_share"] = (float(row.get("rung_seconds_total") or 0.0) / whole) if whole else None
        row["weighted"] = "medians and percentiles weighted by the graphs each batch completed at this size"
    return out


def _the_longest_is_unfinished(rows: list[dict]) -> bool:
    timed = [r for r in rows if isinstance(r.get("max_seconds"), (int, float))]
    if not timed:
        return False
    longest = max(timed, key=lambda r: (float(r["max_seconds"]), bool(r.get("max_unfinished"))))
    return bool(longest.get("max_unfinished"))


def _of_batch(row, payload: dict):
    if not isinstance(row, dict) or row.get("campaign_id") not in (None, ""):
        return row
    return dict(row, campaign_id=payload.get("campaign_id"))


def merge_overviews(payloads: list[dict]) -> dict:
    first = dict(payloads[0])
    batches = [str(p.get("campaign_id")) for p in payloads]
    first.update({
        "campaign_id": STUDY, "batches": batches, "name": f"all {len(batches)} batches",
        "status": "active" if any(p.get("status") == "active" for p in payloads) else first.get("status"),
        "active": [_of_batch(row, p) for p in payloads for row in p.get("active") or []],
        "proposed": [_of_batch(row, p) for p in payloads for row in p.get("proposed") or []],
        "rung_distribution": merge_ladder([p.get("rung_distribution") or [] for p in payloads]),
        "analysis_backlog": sum(int(p.get("analysis_backlog") or 0) for p in payloads),
        "study_scope": {"contract": CONTRACT, "batches": batches,
                        "reading": ("the study's batches together: the live work, the proposed laws and the rung "
                                    "ladder of every batch; the fleet's own parts are the same in each")}})
    for key in ("runtime_counts", "analysis_queue"):
        total: dict = {}
        for p in payloads:
            total = _add(total, p.get(key) or {}) if total else dict(p.get(key) or {})
        first[key] = total
    return first


MERGE_RETRY_SECONDS = 60.0


class Scope:
    def __init__(self, *, batches, landscape_status, schedule_landscape, landscape_ttl, cached_overview,
                 schedule_overview, overview_ttl, host_snapshot, incidents, cache_root: Path, python: str, root: Path,
                 overview_slots: int = 1):
        self.batches, self.landscape_status, self.schedule_landscape = batches, landscape_status, schedule_landscape
        self.landscape_ttl, self.cached_overview, self.schedule_overview = landscape_ttl, cached_overview, schedule_overview
        self.overview_ttl, self.host_snapshot, self.incidents = overview_ttl, host_snapshot, incidents
        self.overview_slots = max(1, int(overview_slots))
        self.cache_root, self.python, self.root = Path(cache_root), python, root
        self.merging = threading.Lock()
        self.merge_failed: dict | None = None

    def serve(self, handler, kind: str, query) -> None:
        (self.landscape if kind == "landscape" else self.overview)(handler, query)

    def paths(self) -> tuple[Path, Path]:
        return self.cache_root / "landscape-study.json", self.cache_root / "landscape-study.meta.json"

    def _merge_in_a_child(self, sources: list[Path], wanted: str | None = None) -> None:
        import subprocess
        import time
        body, meta = self.paths()
        try:
            done = subprocess.run([self.python, "-m", "graph_scale_dynamics.services.api.study_scope", "--out", str(body),
                                   "--meta", str(meta), *map(str, sources)], cwd=self.root, timeout=600,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
            failed = done.returncode != 0
            why = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] if failed else []
        except (OSError, subprocess.SubprocessError) as exc:
            failed, why = True, [f"{type(exc).__name__}: {exc}"]
        finally:
            self.merging.release()
        self.merge_failed = ({"revision": wanted, "at": time.monotonic(), "error": (why or ["the merge failed"])[0][:300]}
                             if failed else None)

    def landscape(self, handler, query) -> None:
        ids = self.batches() or []
        if not ids:
            handler._json({"error": "this folder's study has no batch", "campaign_id": STUDY}, 404)
            return
        metas, sources, waiting, errors, admin, due = [], [], [], {}, handler._privileged(), []
        for place, cid in enumerate(ids):
            body_path, _meta_path, meta, age, refreshing, error = self.landscape_status(cid)
            if error and (meta is None or not body_path.is_file()):
                errors[str(cid)] = str(admin_view.refresh_error(error, admin))[:300]
            missing = meta is None or not body_path.is_file()
            if (missing or age is None or age >= self.landscape_ttl) and not refreshing:
                due.append((not missing, -(age if age is not None else float("inf")), place, cid))
            if missing:
                waiting.append(cid)
            metas.append(meta or {})
            sources.append(body_path)
        for _built, _age, _place, cid in sorted(due):
            if self.schedule_landscape(cid):
                break
        wanted = revision_of([m.get("revision") for m in metas])
        body, meta_path = self.paths()
        try:
            have = json.loads(meta_path.read_text(encoding="utf-8")).get("revision")
        except (OSError, ValueError):
            have = None
        import time
        failed = self.merge_failed if (self.merge_failed or {}).get("revision") == wanted else None
        backing_off = failed is not None and time.monotonic() - failed["at"] < MERGE_RETRY_SECONDS
        if not waiting and have != wanted and not backing_off and self.merging.acquire(blocking=False):
            threading.Thread(target=self._merge_in_a_child, args=(sources, wanted), name="gsd-landscape-study",
                             daemon=True).start()
        if (query.get("meta") or ["0"])[0] == "1":
            ready = have is not None
            handler._json({"campaign_id": STUDY, "contract": CONTRACT, "batches": ids, "revision": have,
                           "pending": not ready, "stale": have != wanted, "waiting_for": waiting,
                           **({"errors": errors} if errors else {}),
                           **({"last_refresh_error": admin_view.refresh_error(failed["error"], admin)}
                              if failed else {}),
                           "retry_after_ms": 500 if not ready or have != wanted else None}, 200 if ready else 202)
        elif body.is_file():
            handler._send_file(body, "application/json; charset=utf-8")
        else:
            handler._json({"campaign_id": STUDY, "pending": True, "waiting_for": waiting, "retry_after_ms": 500}, 202)

    def overview(self, handler, query) -> None:
        ids = self.batches() or []
        if not ids:
            handler._json({"error": "this folder's study has no batch", "campaign_id": STUDY}, 404)
            return
        payloads, stale_any, refreshing_any, oldest, failed = [], False, False, 0.0, {}
        for cid in ids:
            key = (cid, False, False)
            cached, age, refreshing, error = self.cached_overview(key)
            stale = cached is None or age is None or age >= self.overview_ttl
            if stale and not refreshing:
                self.schedule_overview(key)
                refreshing = True
            stale_any, refreshing_any = stale_any or stale, refreshing_any or refreshing
            oldest = max(oldest, age or 0.0)
            if error:
                failed[str(cid)] = error
            if cached is not None:
                payloads.append(cached)
        if len(payloads) < len(ids):
            handler._json({"campaign_id": STUDY, "dashboard_response": {
                "pending": True, "stale": True, "refreshing": True, "retry_after_ms": 250,
                "cache_contract": "gsd-dashboard-async-cache-2",
                "waiting_for": [cid for cid in ids if cid not in {str(p.get("campaign_id")) for p in payloads}]}})
            return
        payload = merge_overviews(payloads)
        payload["access"] = handler._access_payload()
        payload["system_resources"] = self.host_snapshot()
        response = dict(payload.get("dashboard_response") or {})
        builds = [freshness.build_seconds(p) for p in payloads]
        admin = handler._privileged()
        response.update({"pending": False, "stale": bool(stale_any), "refreshing": bool(refreshing_any),
                         "source_age_ms": round(oldest * 1000.0, 1),
                         **freshness.answer(self.overview_ttl, builds, self.overview_slots),
                         "retry_after_ms": 100 if stale_any else None, "incidents": self.incidents(handler),
                         "cache_contract": "gsd-dashboard-async-cache-2"})
        if failed:
            first = sorted(failed, key=lambda cid: (not cid.isdigit(), int(cid) if cid.isdigit() else 0, cid))[0]
            response["last_refresh_error"] = admin_view.refresh_error(
                f"batch {first}: {failed[first]}" + (f" (and {len(failed) - 1} other batch(es))" if len(failed) > 1
                                                     else ""), admin)
            response["refresh_errors"] = {cid: admin_view.refresh_error(text, admin) for cid, text in failed.items()}
        payload["dashboard_response"] = response
        handler._json(payload, 200)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="merge the study's batches' landscapes into one file")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("sources", type=Path, nargs="+")
    args = parser.parse_args(argv)
    started = time.monotonic()
    merged = merge_landscapes([json.loads(path.read_text(encoding="utf-8")) for path in args.sources])
    for target, document in ((args.out, merged),
                             (args.meta, {"campaign_id": STUDY, "revision": merged.get("revision"),
                                          "batches": merged.get("batches"), "generated_utc": merged.get("generated_utc"),
                                          "points": len(merged.get("dimension_points") or []),
                                          "seconds": round(time.monotonic() - started, 2)})):
        partial = target.with_suffix(target.suffix + ".partial")
        partial.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
        partial.replace(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
