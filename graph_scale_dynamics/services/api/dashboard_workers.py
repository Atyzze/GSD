from __future__ import annotations

import json
import threading
import time

DASHBOARD_WORKER_SLOTS_BY_KIND = {"landscape": 1, "heavy": 1}
DASHBOARD_WORKER_SLOTS = sum(DASHBOARD_WORKER_SLOTS_BY_KIND.values())
DASHBOARD_WORKER_RETRY_SECONDS = 60.0
KNOWN_CAMPAIGNS_TTL_SECONDS = 30.0
KNOWN_CAMPAIGNS_REREAD_SECONDS = 2.0


FOCUS_KINDS = ("focus", "seed")


def _design_of(row) -> dict:
    try:
        spec = json.loads(row["spec_json"] or "{}")
    except (KeyError, TypeError, ValueError):
        return {}
    design = spec.get("study_design") if isinstance(spec, dict) else None
    return design if isinstance(design, dict) else {}


class DashboardWorkers:
    def __init__(self, open_repo, db_slots, note=lambda _where, _exc: None):
        self.open_repo, self.db_slots, self.note = open_repo, db_slots, note
        self.slots = {kind: threading.BoundedSemaphore(n) for kind, n in DASHBOARD_WORKER_SLOTS_BY_KIND.items()}
        self.failed_at: dict = {}
        self.ids, self.read_at = frozenset(), None
        self.batch_ids, self.batches_at = [], None
        self.lock = threading.Lock()

    def batches(self) -> list[str]:
        now = time.monotonic()
        with self.lock:
            if self.batches_at is not None and now - self.batches_at < KNOWN_CAMPAIGNS_TTL_SECONDS:
                return list(self.batch_ids)
        if not self.db_slots.acquire(timeout=2.0):
            return list(self.batch_ids)
        repo = None
        try:
            from graph_scale_dynamics.operations.study import LAW_BUDGET_PREFIX
            repo = self.open_repo()
            budgets = {str(r["key"])[len(LAW_BUDGET_PREFIX):] for r in repo.conn.execute(
                "SELECT key FROM control WHERE key LIKE ? AND value<>''", (LAW_BUDGET_PREFIX + "%",)).fetchall()}
            rows = [r for r in repo.conn.execute("SELECT campaign_id,status,spec_json FROM campaigns").fetchall()
                    if str(r["status"] or "") != "archived"]
            designs = {str(r["campaign_id"]): _design_of(r) for r in rows}
            found = [cid for cid in designs if cid in budgets]
            studies = {str(designs[cid].get("study")) for cid in found if designs[cid].get("study") is not None}
            found += [cid for cid, design in designs.items() if cid not in found and design.get("kind") in FOCUS_KINDS
                      and str(design.get("study")) in studies]
            found.sort(key=lambda cid: (not cid.isdigit(), int(cid) if cid.isdigit() else 0, cid))
        except Exception as exc:
            self.note("study batches", exc)
            return list(self.batch_ids)
        finally:
            if repo is not None:
                repo.close()
            self.db_slots.release()
        with self.lock:
            self.batch_ids, self.batches_at = found, now
        return list(found)

    def campaign_exists(self, campaign_id: str) -> bool | None:
        now = time.monotonic()
        with self.lock:
            ids, read_at = self.ids, self.read_at
        if read_at is not None and ((campaign_id in ids and now - read_at < KNOWN_CAMPAIGNS_TTL_SECONDS)
                                    or now - read_at < KNOWN_CAMPAIGNS_REREAD_SECONDS):
            return campaign_id in ids
        if not self.db_slots.acquire(timeout=2.0):
            return True if campaign_id in ids else None
        repo = None
        try:
            repo = self.open_repo()
            ids = frozenset(str(r["campaign_id"]) for r in repo.conn.execute("SELECT campaign_id FROM campaigns").fetchall())
        except Exception as exc:
            self.note("known campaigns", exc)
            return True if campaign_id in ids else None
        finally:
            if repo is not None:
                repo.close()
            self.db_slots.release()
        with self.lock:
            self.ids, self.read_at = ids, now
        return campaign_id in ids

    def take(self, key) -> bool:
        failed = self.failed_at.get(key)
        if failed is not None and time.monotonic() - failed < DASHBOARD_WORKER_RETRY_SECONDS:
            return False
        return self.slots[key[0]].acquire(blocking=False)

    def done(self, key, ok: bool) -> None:
        if ok:
            self.failed_at.pop(key, None)
        else:
            self.failed_at[key] = time.monotonic()
        self.slots[key[0]].release()
