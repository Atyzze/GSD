from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from graph_scale_dynamics import PROJECT_ROOT
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import POLICY_RULE_VERSION as RULE_VERSION, candidate_number_for
from graph_scale_dynamics.domain.version import BUILD_NUMBER, environment_fingerprint, runtime_fingerprint
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.engine.engine import ENGINE_VERSION
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability import (
    live_panel as _live, dashboard_timing, evidence_sources, incidents, memory_ledger,
)
from graph_scale_dynamics.observability.console import error as console_error, iso_utc_now
from graph_scale_dynamics.observability.heartbeat import start_heartbeat_thread
from graph_scale_dynamics.operations import power_sidecar as _power_sidecar, campaign_control, quiet_report
from graph_scale_dynamics.operations.subprocesses import yield_this_thread
from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir
from graph_scale_dynamics.research.law_identity import identity_for
from graph_scale_dynamics.research.proposal_intelligence import SEARCH_SPACE_VERSION
from graph_scale_dynamics.research.report_catalog import REPORT_BY_CODE, REPORT_BY_NUMBER
from graph_scale_dynamics.scheduling.memory import admission_headroom, recorded_lease_reservations
from graph_scale_dynamics.scheduling.runtime import observed_analysis_profile, observed_profile, predict_wall
from graph_scale_dynamics.services.api import (
    admin_link, admin_view, campaign_manager, dashboard_limit, landscape_inputs, readings_route, study_scope,
)
from graph_scale_dynamics.services.api.law_dynamics import law_dynamics_of
from graph_scale_dynamics.services.api.dashboard_workers import DashboardWorkers
from graph_scale_dynamics.services.api.host import (
    _HOST_SNAPSHOT, _note_swallowed, _published_sidecar_reading, _stop_btop_sidecar, host_snapshot,
)
from graph_scale_dynamics.services.api.overview import (
    _age_seconds, _candidate_stability, _ensemble_code_for, _published_channels, _stranded_work_alerts,
    _transitions_from_rungs, build_fast_overview, equilibration_rows, json_bytes, law_label, normalize_base_path,
    public_row,
)

ROOT = PROJECT_ROOT

CLIENT_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)

LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1", ""})
MAX_REQUEST_BYTES = 1_000_000
SOCKET_TIMEOUT_SECONDS = 60.0
ANSWER_CHUNK_BYTES = 1 << 20

DASHBOARD_OVERVIEW_TTL_SECONDS = ticks(1)
DASHBOARD_OVERVIEW_TTL_PAUSED_SECONDS = ticks(4)
DASHBOARD_LANDSCAPE_TTL_SECONDS = ticks(4)
DASHBOARD_HEAVY_TTL_SECONDS = ticks(8)

DASHBOARD_HEAVY_SECTION_MODES = ("lazy", "always", "off")


_DB_UNAVAILABLE_LOG = {"last": 0.0, "suppressed": 0}


def _log_database_unavailable(exc: BaseException) -> None:
    now = time.monotonic()
    if now - _DB_UNAVAILABLE_LOG["last"] < 60.0:
        _DB_UNAVAILABLE_LOG["suppressed"] += 1
        return
    suppressed = _DB_UNAVAILABLE_LOG["suppressed"]
    _DB_UNAVAILABLE_LOG["last"] = now
    _DB_UNAVAILABLE_LOG["suppressed"] = 0
    print(f"[api] database unavailable ({suppressed} further request(s) suppressed in the "
          f"last minute): {str(exc).splitlines()[0][:200]}", file=sys.stderr, flush=True)


def build_handler(db_path: str, blobs_path: str, admin_token: str, port: int,
                  *, bind_host: str = "127.0.0.1", allowed_hosts: tuple[str, ...] = (),
                  base_path: str = "",
                  exploration_map_mode: str = "lazy",
                  past_research_mode: str = "lazy",
                  report_root: str | Path | None = None,
                  report_campaign_id: str | None = None,
                  internal_token: str | None = None,
                  snapshot_tmp: str | Path | None = None,
                  calibration_root: str | Path | None = None,
                  repository_root: str | Path | None = None):
    base_path = normalize_base_path(base_path)
    link = admin_link.AdminLink(admin_token)
    _live.RESUME_ROOT = Path(blobs_path)
    readings_route.BLOBS_ROOT = Path(blobs_path)
    from graph_scale_dynamics.calibration import durable_artifact_path as _durable_path
    durable_calibration_root = (Path(repository_root).resolve() if repository_root is not None
                                else _durable_path().parents[1])
    if exploration_map_mode not in DASHBOARD_HEAVY_SECTION_MODES:
        raise ValueError(f"invalid exploration_map_mode {exploration_map_mode!r}")
    if past_research_mode not in DASHBOARD_HEAVY_SECTION_MODES:
        raise ValueError(f"invalid past_research_mode {past_research_mode!r}")
    launch_report_campaign = str(report_campaign_id) if report_campaign_id is not None else None
    launch_report_root = Path(report_root).resolve() if report_root is not None else None
    if launch_report_root is not None:
        (launch_report_root / "reports").mkdir(parents=True, exist_ok=True)
        readings_route.study_route.REPORT_ROOT = launch_report_root

    from graph_scale_dynamics.operations.report_home import base_of, read_pointer, root_for, write_pointer
    _home_cache = {"at": 0.0, "campaign": launch_report_campaign}

    def report_campaign_now() -> str | None:
        if launch_report_campaign is None:
            return None
        now = time.monotonic()
        if now - _home_cache["at"] > 2.0:
            try:
                with Repo(db_path) as flag_repo:
                    flagged = str(campaign_control.reporting_focus(flag_repo) or "")
                    if flagged and flag_repo.campaign(flagged) is not None:
                        _home_cache["campaign"] = flagged
            except Exception as exc:
                _note_swallowed("report_campaign_now", exc)
            _home_cache["at"] = now
            base, campaign = (base_of(launch_report_root) if launch_report_root else None), _home_cache["campaign"]
            if base is not None and campaign and read_pointer(base) != str(campaign):
                try:
                    write_pointer(base, str(campaign))
                except OSError as exc:
                    _note_swallowed("report_campaign_now", exc)
        return _home_cache["campaign"]

    def report_root_now() -> Path | None:
        if launch_report_root is None:
            return None
        campaign_now = report_campaign_now()
        if campaign_now is None or campaign_now == launch_report_campaign:
            return launch_report_root
        root = root_for(base_of(launch_report_root), campaign_now)
        (root / "reports").mkdir(parents=True, exist_ok=True)
        return root
    internal_token = str(internal_token or "")
    calibration_root_path = (Path(calibration_root).resolve() if calibration_root is not None
                             else Path(blobs_path).resolve().parent / "calibration")
    snapshot_tmp_path = Path(snapshot_tmp).resolve() if snapshot_tmp is not None else (ROOT / "var" / "tmp")
    snapshot_tmp_path.mkdir(parents=True, exist_ok=True)
    dashboard_cache_root = snapshot_tmp_path / "dashboard-cache"
    dashboard_cache_root.mkdir(parents=True, exist_ok=True)
    overview_cache: dict[tuple[str, bool, bool], dict] = {}
    overview_cache_built_at: dict[tuple[str, bool, bool], float] = {}
    overview_refreshing: set[tuple[str, bool, bool]] = set()
    overview_refresh_errors: dict[tuple[str, bool, bool], str] = {}
    overview_cache_lock = threading.Lock()
    heavy_refreshing: set[tuple[str, bool, bool]] = set()
    heavy_refresh_errors: dict[tuple[str, bool, bool], str] = {}
    heavy_cache_lock = threading.Lock()
    heavy_ttl_seconds = max(1.0, float(os.environ.get("GSD_DASHBOARD_HEAVY_TTL_SECONDS", DASHBOARD_HEAVY_TTL_SECONDS)))
    heavy_timeout_seconds = max(1.0, float(os.environ.get("GSD_DASHBOARD_HEAVY_TIMEOUT_SECONDS", "3600")))
    landscape_refreshing: set[str] = set()
    landscape_refresh_errors: dict[str, str] = {}
    landscape_cache_lock = threading.Lock()
    landscape_ttl_seconds = max(1.0, float(os.environ.get("GSD_DASHBOARD_LANDSCAPE_TTL_SECONDS", DASHBOARD_LANDSCAPE_TTL_SECONDS)))
    landscape_timeout_seconds = max(1.0, float(os.environ.get("GSD_DASHBOARD_LANDSCAPE_TIMEOUT_SECONDS", "900.0")))
    overview_ttl_seconds = max(0.1, float(os.environ.get("GSD_DASHBOARD_OVERVIEW_TTL_SECONDS", DASHBOARD_OVERVIEW_TTL_SECONDS)))
    overview_ttl_paused_seconds = max(
        overview_ttl_seconds,
        float(os.environ.get("GSD_DASHBOARD_OVERVIEW_TTL_PAUSED_SECONDS", DASHBOARD_OVERVIEW_TTL_PAUSED_SECONDS)))
    dashboard_db_concurrency = max(1, int(os.environ.get("GSD_DASHBOARD_DB_CONCURRENCY", "4")))
    dashboard_db_slots = threading.BoundedSemaphore(dashboard_db_concurrency)
    workers = DashboardWorkers(lambda: Repo(db_path), dashboard_db_slots, note=_note_swallowed)

    def _refresh_overview_cache(key: tuple[str, bool, bool]) -> None:
        campaign_id, _include_exploration, _include_past = key
        yield_this_thread()
        acquired = dashboard_db_slots.acquire(timeout=5.0)
        if not acquired:
            with overview_cache_lock:
                overview_refresh_errors[key] = "dashboard database capacity busy"
                overview_refreshing.discard(key)
            return
        repo = None
        try:
            repo = Repo(db_path)
            payload = build_fast_overview(repo, campaign_id)
            io_summary = dict(payload.get("io_summary") or {})
            scratch = choose_volatile_dir(
                namespace=f"blobstore:{Path(blobs_path).resolve()}",
                allow_persistent_fallback=False,
            )
            scratch["staging_path"] = (
                str(Path(str(scratch["path"])) / "staging")
                if scratch.get("path") else None
            )
            io_summary["scratch_backend"] = scratch
            payload["io_summary"] = io_summary
            if "error" not in payload:
                if report_campaign_now() is not None and campaign_id == report_campaign_now():
                    payload["reporting"] = {
                        "integrated": True,
                        "base_path": f"{base_path}/reports" if base_path else "/reports",
                    }
                else:
                    payload["reporting"] = {"integrated": False}
                sections = payload.setdefault("dashboard_sections", {})
                sections.setdefault("exploration_map", {})["mode"] = (
                    "off" if exploration_map_mode == "off" else "lazy")
                sections.setdefault("past_research", {})["mode"] = (
                    "off" if past_research_mode == "off" else "lazy")
                payload.setdefault("dashboard_response", {})
                payload["dashboard_response"].update({
                    "pending": False,
                    "stale": False,
                    "cache_contract": "gsd-dashboard-async-cache-2",
                    "db_concurrency_limit": dashboard_db_concurrency,
                })
            with overview_cache_lock:
                overview_cache[key] = payload
                overview_cache_built_at[key] = time.monotonic()
                overview_refresh_errors.pop(key, None)
                incidents.clear("api", "overview refresh")
        except Exception as exc:
            fault = incidents.record("api", "overview refresh", exc,
                                     detail=f"campaign {key[0]}")
            with overview_cache_lock:
                overview_refresh_errors[key] = (
                    f"{fault['error']}"
                    + (f" at {fault['origin']}" if fault.get("origin") else ""))
        finally:
            if repo is not None:
                repo.close()
            dashboard_db_slots.release()
            with overview_cache_lock:
                overview_refreshing.discard(key)

    def _schedule_overview_refresh(key: tuple[str, bool, bool]) -> bool:
        with overview_cache_lock:
            if key in overview_refreshing:
                return False
            overview_refreshing.add(key)
        threading.Thread(
            target=_refresh_overview_cache, args=(key,),
            name=f"gsd-overview-{key[0]}", daemon=True,
        ).start()
        return True

    def _cached_overview(key: tuple[str, bool, bool]) -> tuple[dict | None, float | None, bool, str | None]:
        now = time.monotonic()
        with overview_cache_lock:
            cached = overview_cache.get(key)
            built = overview_cache_built_at.get(key)
            refreshing = key in overview_refreshing
            error = overview_refresh_errors.get(key)
        age = None if not built else max(0.0, now - built)
        return cached, age, refreshing, error

    def _mark_overview_stale(campaign_id: str | None = None) -> None:
        with overview_cache_lock:
            for key in list(overview_cache_built_at):
                if campaign_id is None or key[0] == str(campaign_id):
                    overview_cache_built_at[key] = 0.0

    def _landscape_paths(campaign_id: str) -> tuple[Path, Path]:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(campaign_id))[:48] or "campaign"
        return (dashboard_cache_root / f"landscape-{safe}.json",
                dashboard_cache_root / f"landscape-{safe}.meta.json")

    def _landscape_status(campaign_id: str) -> tuple[Path, Path, dict | None, float | None, bool, str | None]:
        body_path, meta_path = _landscape_paths(campaign_id)
        try:
            age = max(0.0, time.time() - body_path.stat().st_mtime)
        except OSError:
            age = None
        meta = None
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except (OSError, json.JSONDecodeError):
            meta = None
        with landscape_cache_lock:
            return (body_path, meta_path, meta, age,
                    str(campaign_id) in landscape_refreshing,
                    landscape_refresh_errors.get(str(campaign_id)))

    def _refresh_landscape(campaign_id: str) -> None:
        campaign_id = str(campaign_id)
        body_path, meta_path = _landscape_paths(campaign_id)
        try:
            inputs = landscape_inputs.read_now(lambda: Repo(db_path), dashboard_db_slots, _note_swallowed)
            if not landscape_inputs.kept(inputs, body_path, meta_path):
                cmd = [sys.executable, "-m", "graph_scale_dynamics.services.api.landscape_worker",
                       "--db", db_path, "--campaign", campaign_id,
                       "--output", str(body_path), "--meta", str(meta_path), *landscape_inputs.argv(inputs)]
                completed = subprocess.run(
                    cmd, cwd=ROOT, timeout=landscape_timeout_seconds,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                if completed.returncode != 0:
                    detail = (completed.stderr or "landscape worker failed")[-2000:]
                    raise RuntimeError(detail)
            with landscape_cache_lock:
                landscape_refresh_errors.pop(campaign_id, None)
        except subprocess.TimeoutExpired:
            with landscape_cache_lock:
                landscape_refresh_errors[campaign_id] = "landscape worker timed out"
        except Exception as exc:
            with landscape_cache_lock:
                landscape_refresh_errors[campaign_id] = f"{type(exc).__name__}: {exc}"
        finally:
            workers.done(("landscape", campaign_id), campaign_id not in landscape_refresh_errors)
            with landscape_cache_lock:
                landscape_refreshing.discard(campaign_id)

    def _schedule_landscape_refresh(campaign_id: str) -> bool:
        campaign_id = str(campaign_id)
        with landscape_cache_lock:
            if campaign_id in landscape_refreshing or not workers.take(("landscape", campaign_id)):
                return False
            landscape_refreshing.add(campaign_id)
        threading.Thread(
            target=_refresh_landscape, args=(campaign_id,),
            name=f"gsd-landscape-{campaign_id}", daemon=True,
        ).start()
        return True

    study = study_scope.Scope(
        batches=workers.batches, landscape_status=_landscape_status, schedule_landscape=_schedule_landscape_refresh,
        landscape_ttl=landscape_ttl_seconds, cached_overview=_cached_overview, schedule_overview=_schedule_overview_refresh,
        overview_ttl=overview_ttl_seconds, host_snapshot=host_snapshot,
        incidents=lambda handler: admin_view.incidents(incidents.recent(4), handler._privileged()),
        cache_root=dashboard_cache_root, python=sys.executable, root=ROOT)

    def _heavy_cache_path(key: tuple[str, bool, bool]) -> Path:
        campaign_id, include_exploration, include_past = key
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", campaign_id)[:48] or "campaign"
        suffix = ("e" if include_exploration else "") + ("p" if include_past else "")
        return snapshot_tmp_path / f"dashboard-heavy-{safe}-{suffix or 'none'}.json"

    def _heavy_status(key: tuple[str, bool, bool]) -> tuple[Path, float | None, bool, str | None]:
        path = _heavy_cache_path(key)
        try:
            age = max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            age = None
        with heavy_cache_lock:
            return path, age, key in heavy_refreshing, heavy_refresh_errors.get(key)

    def _refresh_heavy_cache(key: tuple[str, bool, bool]) -> None:
        campaign_id, include_exploration, include_past = key
        target = _heavy_cache_path(key)
        try:
            cmd = [sys.executable, "-m", "graph_scale_dynamics.services.api.overview_worker",
                   "--db", db_path, "--campaign", campaign_id, "--output", str(target)]
            if include_exploration:
                cmd.append("--exploration")
            if include_past:
                cmd.append("--past")
            completed = subprocess.run(
                cmd, cwd=ROOT, timeout=heavy_timeout_seconds,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or "heavy overview worker failed")[-2000:]
                raise RuntimeError(detail)
            with heavy_cache_lock:
                heavy_refresh_errors.pop(key, None)
        except subprocess.TimeoutExpired:
            with heavy_cache_lock:
                heavy_refresh_errors[key] = "heavy overview worker timed out"
        except Exception as exc:
            incidents.record("api", "heavy overview refresh", exc)
            with heavy_cache_lock:
                heavy_refresh_errors[key] = f"{type(exc).__name__}: {exc}"
        finally:
            workers.done(("heavy", key), key not in heavy_refresh_errors)
            with heavy_cache_lock:
                heavy_refreshing.discard(key)

    def _schedule_heavy_refresh(key: tuple[str, bool, bool]) -> bool:
        with heavy_cache_lock:
            if key in heavy_refreshing or not workers.take(("heavy", key)):
                return False
            heavy_refreshing.add(key)
        threading.Thread(
            target=_refresh_heavy_cache, args=(key,),
            name=f"gsd-overview-heavy-{key[0]}", daemon=True,
        ).start()
        return True

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

        def handle(self):
            try:
                super().handle()
            except CLIENT_DISCONNECTS:
                self.close_connection = True

        def log_message(self, *args):
            pass

        def _send_bytes(self, body: bytes, content_type: str, code: int = 200) -> bool:
            try:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
                )
                self.end_headers()
                for start in range(0, len(body), ANSWER_CHUNK_BYTES):
                    self.wfile.write(memoryview(body)[start:start + ANSWER_CHUNK_BYTES])
                return True
            except CLIENT_DISCONNECTS:
                return False

        def _json(self, payload, code=200):
            if code >= 500:
                payload, said = admin_view.answer_for(payload, code, self._privileged())
                if said:
                    console_error("api", f"{said} (from {self._route_path()}, shown without its detail)")
            return self._send_bytes(json_bytes(payload), "application/json; charset=utf-8", code)

        @staticmethod
        def _allowed_hostname(hostname: str) -> bool:
            hostname = (hostname or "").strip().lower()
            if hostname in LOOPBACK_HOSTNAMES or hostname in set(allowed_hosts):
                return True
            if bind_host not in ("0.0.0.0", "::", "") and hostname == bind_host.lower():
                return True
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return False
            return bool(address.is_loopback or address.is_private or address.is_link_local)

        def _request_hostname(self) -> str:
            host = (self.headers.get("Host") or "").strip().lower()
            if host.startswith("[") and "]" in host:
                return host[1:host.index("]")]
            return host.rsplit(":", 1)[0] if host.count(":") == 1 else host

        def _client_is_loopback(self) -> bool:
            try:
                return ipaddress.ip_address(str(self.client_address[0])).is_loopback
            except (ValueError, IndexError, TypeError):
                return False

        @staticmethod
        def _token_matches(supplied: str, expected: str) -> bool:
            if not supplied or not expected:
                return False
            return secrets.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                                          expected.encode("utf-8", "surrogatepass"))

        def _supplied_admin_token(self) -> str:
            return self.headers.get("X-GSD-Admin-Token") or ""

        def _admin_token_valid(self) -> bool:
            return link.matches(self._supplied_admin_token())

        def _local_admin(self) -> bool:
            return self._client_is_loopback() and self._admin_token_valid()

        def _privileged(self) -> bool:
            return self._client_is_loopback() and (self._admin_token_valid() or self._token_matches(
                self.headers.get("X-GSD-Internal-Token") or "", internal_token or ""))

        def _internal_authorized(self) -> bool:
            supplied = self.headers.get("X-GSD-Internal-Token") or ""
            if (not self._client_is_loopback()
                    or not self._token_matches(supplied, internal_token or "")):
                self._json({"error": "internal loopback capability required"}, 403)
                return False
            return True

        def _send_file(self, path: Path, content_type: str, code: int = 200) -> bool:
            try:
                size = path.stat().st_size
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with path.open("rb") as handle:
                    while True:
                        chunk = handle.read(ANSWER_CHUNK_BYTES)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                return True
            except CLIENT_DISCONNECTS:
                return False

        def _access_payload(self) -> dict:
            return link.access(self._supplied_admin_token(), loopback=self._client_is_loopback())

        def _route_path(self) -> str:
            path = urlparse(self.path).path
            if base_path and (path == base_path or path.startswith(base_path + "/")):
                path = path[len(base_path):] or "/"
            return path

        def _host_authorized(self) -> bool:
            hostname = self._request_hostname()
            if not self._allowed_hostname(hostname):
                self._json({"error": "host not allowed"}, 403)
                return False
            return True

        def _admin_authorized(self) -> bool:
            if not self._client_is_loopback():
                link.refused(self._supplied_admin_token(), self._route_path())
                self._json({"error": "local admin access required"}, 403)
                return False
            if not self._admin_token_valid():
                link.refused(self._supplied_admin_token(), self._route_path())
                self._json(link.refusal(self._supplied_admin_token(), "admin token required"), 403)
                return False
            return True

        def _json_request_authorized(self) -> bool:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._json({"error": "application/json required"}, 415)
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlparse(origin)
                origin_host = (parsed.hostname or "").lower()
                if (parsed.scheme not in ("http", "https")
                        or not self._allowed_hostname(origin_host)
                        or origin_host != self._request_hostname()):
                    self._json({"error": "origin not allowed"}, 403)
                    return False
            return True

        def _pause_authorized(self) -> bool:
            if self._local_admin():
                return True
            link.refused(self._supplied_admin_token(), self._route_path())
            self._json(link.refusal(self._supplied_admin_token(),
                                    "pause/resume needs the admin token (the admin link, through the dashboard)"), 403)
            return False

        def _answering(self, handle) -> None:
            try:
                handle()
            except (ValueError, UnicodeError) as exc:
                try:
                    self._json({"error": "malformed request", "detail": type(exc).__name__}, 400)
                except OSError:
                    pass

        def do_POST(self):
            self._answering(self._post)

        def do_GET(self):
            self._answering(lambda: dashboard_limit.serve(self, dashboard_db_slots, self._get))

        def _post(self):
            if not self._host_authorized():
                return
            if not self._json_request_authorized():
                return
            parts = [p for p in self._route_path().split("/") if p]
            if readings_route.handles(parts):
                return self._admin_authorized() and readings_route.post(self, db_path, parts, MAX_REQUEST_BYTES)

            if parts[:2] == ["internal", "runtime-imports"] and len(parts) == 3:
                if not self._internal_authorized():
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode() or "{}")
                    names = [str(n) for n in (body.get("modules") or [])]
                    with Repo(db_path) as repo:
                        changed = repo.publish_runtime_imports(parts[2], names=names)
                    self._json({"service": parts[2], "modules": len(names), "changed": bool(changed)})
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return

            is_pause = parts[:2] == ["api", "pause"]
            is_report_trigger = parts[:3] == ["api", "reports", "trigger"]
            is_manage = parts[:3] == ["api", "campaigns", "manage"]
            if is_pause:
                if not self._pause_authorized():
                    return
            elif is_report_trigger:
                if not self._admin_authorized():
                    return
            elif is_manage:
                if not self._admin_authorized():
                    return
            else:
                self._json({"error": "not found"}, 404)
                return
            if is_manage:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._json({"error": "request body too large"}, 413)
                    return
                sent = campaign_manager.body_from(self.rfile.read(length))
                link.accepted("campaigns/manage", str((sent or {}).get("action") or "") if isinstance(sent, dict) else None)
                try:
                    with Repo(db_path) as manage_repo:
                        payload, code = campaign_manager.handle(manage_repo, sent)
                except Exception as exc:  # noqa: BLE001
                    payload, code = {"error": f"{type(exc).__name__}: {str(exc)[:300]}",
                                     "reading": "nothing past the point it failed was done; read the page again"}, 500
                self._json(payload, code)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._json({"error": "invalid Content-Length"}, 400)
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._json({"error": "request body too large"}, 413)
                return
            try:
                body = json.loads(self.rfile.read(length).decode() or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "invalid JSON"}, 400)
                return

            if not dashboard_db_slots.acquire(timeout=2.0):
                self._json({"error": "dashboard database capacity busy", "retryable": True}, 503)
                return
            repo = None
            try:
                try:
                    repo = Repo(db_path)
                except DatabaseOperationalError as exc:
                    if exc.transient:
                        self._json({
                            "error": "database busy; retry control action",
                            "retryable": True, "sqlstate": exc.sqlstate,
                        }, 503)
                        return
                    raise
                link.accepted("pause" if is_pause else "reports/trigger",
                              str(body.get("paused") if is_pause else body.get("action") or "start"))
                if is_pause:
                    requested = body.get("paused")
                    if not isinstance(requested, bool):
                        self._json({"error": "paused must be boolean"}, 400)
                        return
                    current = repo.get_flag("paused") == "1"
                    if not requested and (held := quiet_report.holding(repo)):
                        self._json({"error": held}, 409)
                        return
                    if not requested and requested != current:
                        repo.set_flag("paused", "0")
                    cancellation = None
                    if requested:
                        if requested != current:
                            repo.set_flag("paused", "1")
                        cancel_active = getattr(repo, "operator_pause_cancel_active_work", None)
                        cancellation = (
                            cancel_active(reason="user cancelled by dashboard PAUSE")
                            if callable(cancel_active) else None
                        )
                    _mark_overview_stale(None)
                    self._json({"paused": repo.get_flag("paused") == "1", "cancellation": cancellation})
                elif is_report_trigger:
                    if report_campaign_now() is None:
                        self._json({"error": "integrated reporting is unavailable"}, 409)
                        return
                    payload, code = quiet_report.request(repo, str(body.get("campaign_id") or ""), str(body.get(
                        "action") or "start"), report_root=launch_report_root, db=db_path, api_port=port)
                    _home_cache["at"] = 0.0
                    if quiet_report.in_progress(repo):
                        quiet_report.ensure_runner(lambda: Repo(db_path))
                    self._json(dict(payload, access=self._access_payload()), code)

            except CLIENT_DISCONNECTS:
                return
            except Exception as exc:
                request_id = uuid.uuid4().hex[:12]
                console_error(
                    "api",
                    f"{request_id}: {type(exc).__name__}: {exc}\n"
                    + traceback.format_exc(limit=16),
                )
                self._json({"error": "internal server error", "request_id": request_id}, 500)
            finally:
                if repo is not None:
                    repo.close()
                dashboard_db_slots.release()

        def _get(self):
            if not self._host_authorized():
                return
            path = self._route_path()
            parts = [p for p in path.split("/") if p]
            if parts == ["api", "access"]:
                return self._json(self._access_payload())
            if readings_route.handles(parts):
                return readings_route.get(self, db_path, parts)
            if path in ("/", "/index.html", "/calibration") or path == "/reports" or path.startswith("/reports/"):
                self._json({"error": "web assets are served by the separate web process"}, 404)
                return
            parts = [p for p in path.split("/") if p]
            if parts[:2] == ["api", "calibration"] and len(parts) in (2, 3):
                from graph_scale_dynamics.calibration import resolve_table
                target, document, kind = resolve_table(durable_calibration_root, calibration_root_path.parent)
                if document is None:
                    self._json({
                        "available": False,
                        "hint": ("no calibration table in force; `main.py run` or `main.py serve` "
                                 "computes it in the foreground before starting, or run "
                                 "`python3 tools/probe_calibration.py --probe-ladders` by hand"),
                        "expected_path": str(target),
                    })
                    return
                if len(parts) == 3 and parts[2] in ("cells", "table"):
                    self._json(document if parts[2] == "table" else {
                        "available": True, "path": str(target), "source": kind, "cells": document.get("cells") or {}})
                    return
                if len(parts) == 3:
                    self._json({"error": "unknown calibration resource"}, 404)
                    return
                summary = {k: v for k, v in document.items() if k != "cells"}
                from graph_scale_dynamics.research.probe_atlas import build_probe_atlas
                try:
                    summary["atlas"] = build_probe_atlas(document)
                    try:
                        from graph_scale_dynamics.scheduling.base_block import base_sizes as _bs
                        with Repo(db_path) as _rungs_repo:
                            _focus = campaign_control.reporting_focus(_rungs_repo)
                            _home = _rungs_repo.campaign(_focus) if _focus else None
                        summary["atlas"]["campaign_rungs"] = (
                            [int(n) for n in _bs((_home or {}).get("spec") or {})] if _home else [])
                    except Exception as exc:
                        summary["atlas"]["campaign_rungs"] = []
                        summary["atlas"]["campaign_rungs_note"] = f"{type(exc).__name__}: {exc}"
                        _note_swallowed("atlas campaign rungs", exc)
                except Exception as exc:
                    summary["atlas"] = {"error": f"{type(exc).__name__}: {exc}"}
                self._json({"available": True, "path": str(target), "source": kind,
                            "cell_count": len(document.get("cells") or {}), **summary})
                return
            if parts[:2] == ["api", "memory-ledger"] and len(parts) == 2:
                try:
                    with Repo(db_path) as repo_for_evidence:
                        pids: dict[str, list[int]] = {}
                        for hb in repo_for_evidence.conn.execute(
                                "SELECT service,pid,sampled_utc FROM service_heartbeats").fetchall():
                            if _age_seconds(hb["sampled_utc"]) > 120:
                                continue
                            name = str(hb["service"])
                            role = ("executor" if name.startswith("executor-") else name.rsplit("-", 1)[0]
                                    if "-" in name else name)
                            pids.setdefault(role, []).append(int(hb["pid"]))
                        try:
                            reservations = recorded_lease_reservations(repo_for_evidence.conn)
                            reservations["admission"] = admission_headroom(repo_for_evidence.conn)
                            reservations["budget"] = reservations["admission"]["budget_bytes"]
                        except Exception as exc:
                            _note_swallowed("do_GET", exc)
                            reservations = None
                    try:
                        scratch = choose_volatile_dir(
                            namespace=f"blobstore:{Path(blobs_path).resolve()}",
                            allow_persistent_fallback=False)
                        scratch_root = Path(str(scratch["path"])) if scratch.get("path") else None
                    except Exception as exc:
                        _note_swallowed("do_GET", exc)
                        scratch_root = None
                    self._json(memory_ledger.build_ledger(pids, scratch_root=scratch_root,
                                                          reservations=reservations))
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if parts[:2] == ["api", "performance"] and len(parts) == 3:
                try:
                    with Repo(db_path) as repo_for_evidence:
                        self._json(evidence_sources.performance_payload(repo_for_evidence, str(parts[2])))
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if parts[:2] == ["api", "schema"] and len(parts) == 2:
                try:
                    with Repo(db_path) as repo_for_evidence:
                        self._json(evidence_sources.schema_payload(repo_for_evidence))
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if parts[:2] == ["api", "supervisor-log"] and len(parts) == 2:
                if not self._privileged():
                    return self._json({"error": "admin token required: the services' console is the admin's"}, 403)
                return admin_view.supervisor_log(self, calibration_root_path.parent)
            if parts[:2] == ["api", "stranded"] and len(parts) == 3:
                try:
                    with Repo(db_path) as repo_for_evidence:
                        campaign = repo_for_evidence.campaign(str(parts[2]))
                        if campaign is None:
                            self._json({"error": "unknown campaign"}, 404)
                            return
                        version = (campaign.get("spec") or {}).get("analysis_version", ANALYSIS_VERSION)
                        alerts = _stranded_work_alerts(repo_for_evidence, str(parts[2]), version)
                        stranded = next((a for a in alerts if a.get("code") == "STRANDED_SCIENTIFIC_WORK"), None)
                        ids = [c.get("candidate_id") for c in ((stranded or {}).get("candidates") or [])]
                        payload = evidence_sources.stranded_payload(repo_for_evidence, str(parts[2]), ids)
                        payload["alert"] = stranded
                        self._json(payload)
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if parts[:3] == ["api", "reports", "status"] and len(parts) == 4:
                campaign_id = str(parts[3])
                try:
                    with Repo(db_path) as repo:
                        flight = quiet_report.work_in_flight(repo)
                        quiet = quiet_report.state(repo)
                        focus = campaign_control.reporting_focus(repo)
                    manifest, root_now = None, report_root_now()
                    asked = root_for(base_of(root_now), campaign_id) / "manifest.json" if root_now is not None else None
                    if asked is not None and asked.is_file():
                        try:
                            manifest = json.loads(asked.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            manifest = None
                    self._json({
                        "campaign_id": campaign_id,
                        "manifest": manifest, "access": self._access_payload(),
                        "in_flight": flight, "quiet_report": quiet,
                        "reporting_campaign_id": focus,
                    })
                except Exception as exc:
                    self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            if parts[:2] == ["api", "reports"] and len(parts) == 3:
                requested = str(parts[2]).strip()
                definition = REPORT_BY_NUMBER.get(int(requested)) if requested.isdigit() else None
                code = definition.code if definition is not None else ""
                if code not in REPORT_BY_CODE or report_root_now() is None:
                    self._json({"error": "report not found"}, 404)
                    return
                target = report_root_now() / "reports" / f"{code}.json"
                if not target.is_file():
                    self._json({"error": "report snapshot not generated yet", "code": code}, 404)
                    return
                try:
                    self._send_file(target, "application/json; charset=utf-8")
                except CLIENT_DISCONNECTS:
                    pass
                return
            query = parse_qs(urlparse(self.path).query)
            overview_key = None
            if len(parts) == 3 and parts[:2] in (["api", "landscape"], ["api", "overview"]) and parts[2] == study_scope.STUDY:
                return study.serve(self, parts[1], query)
            if len(parts) == 3 and parts[:2] in (["api", "landscape"], ["api", "overview"]):
                exists = workers.campaign_exists(str(parts[2]))
                if exists is None:
                    self._json({"error": "the campaign list could not be read now; ask again",
                                "campaign_id": str(parts[2]), "retryable": True, "retry_after_ms": 2000}, 503)
                    return
                if not exists:
                    self._json({"error": "unknown campaign", "campaign_id": str(parts[2])}, 404)
                    return
            if parts[:2] == ["api", "landscape"] and len(parts) == 3:
                campaign_id = str(parts[2])
                body_path, meta_path, meta, age, refreshing, refresh_error = _landscape_status(campaign_id)
                stale = age is None or age >= landscape_ttl_seconds
                if stale and not refreshing:
                    refreshing = _schedule_landscape_refresh(campaign_id)
                meta_only = (query.get("meta") or ["0"])[0] == "1"
                if meta_only:
                    payload = dict(meta or {})
                    payload.update({
                        "campaign_id": campaign_id,
                        "pending": meta is None,
                        "stale": bool(stale),
                        "refreshing": bool(refreshing),
                        "source_age_ms": None if age is None else round(age * 1000.0, 1),
                        "retry_after_ms": 250 if meta is None else (1000 if stale else None),
                        "last_refresh_error": admin_view.refresh_error(refresh_error, self._privileged()),
                        "incidents": admin_view.incidents(incidents.recent(4), self._privileged()),
                        "cache_contract": "gsd-authoritative-landscape-file-1",
                    })
                    self._json(payload, 202 if meta is None else 200)
                    return
                if body_path.is_file():
                    self._send_file(body_path, "application/json; charset=utf-8")
                else:
                    self._json({
                        "campaign_id": campaign_id, "pending": True,
                        "refreshing": bool(refreshing), "retry_after_ms": 250,
                        "last_refresh_error": admin_view.refresh_error(refresh_error, self._privileged()),
                        "incidents": admin_view.incidents(incidents.recent(4), self._privileged()),
                        "cache_contract": "gsd-authoritative-landscape-file-1",
                    }, 202)
                return

            if parts[:2] == ["api", "overview"] and len(parts) == 3:
                want_exploration = (query.get("exploration") or ["0"])[0] == "1"
                want_past = (query.get("past") or ["0"])[0] == "1"
                if want_exploration or want_past:
                    heavy_key = (parts[2], bool(want_exploration), bool(want_past))
                    path, heavy_age, heavy_running, heavy_error = _heavy_status(heavy_key)
                    heavy_stale = heavy_age is None or heavy_age >= heavy_ttl_seconds
                    if heavy_stale and not heavy_running:
                        heavy_running = _schedule_heavy_refresh(heavy_key)
                    if path.is_file():
                        self._send_file(path, "application/json; charset=utf-8")
                    else:
                        self._json({
                            "campaign_id": parts[2],
                            "dashboard_response": {
                                "heavy_pending": True, "refreshing": heavy_running,
                                "retry_after_ms": 500,
                                "cache_contract": "gsd-dashboard-heavy-file-1",
                                "last_refresh_error": admin_view.refresh_error(heavy_error, self._privileged()),
                            },
                        })
                    return

                overview_key = (parts[2], False, False)
                cached, age, refreshing, refresh_error = _cached_overview(overview_key)
                ttl = (overview_ttl_paused_seconds
                       if (cached or {}).get("paused") else overview_ttl_seconds)
                stale = cached is None or age is None or age >= ttl
                if stale and not refreshing:
                    _schedule_overview_refresh(overview_key)
                    refreshing = True
                if cached is None:
                    self._json({
                        "campaign_id": parts[2],
                        "access": self._access_payload(),
                        "dashboard_response": {
                            "pending": True, "stale": True, "refreshing": refreshing,
                            "retry_after_ms": 100,
                            "cache_contract": "gsd-dashboard-async-cache-2",
                            "last_refresh_error": admin_view.refresh_error(refresh_error, self._privileged()),
                            "incidents": admin_view.incidents(incidents.recent(4), self._privileged()),
                        },
                    })
                    return
                payload = dict(cached)
                payload["access"] = self._access_payload()
                payload["system_resources"] = host_snapshot()
                response_meta = dict(payload.get("dashboard_response") or {})
                response_meta.update({
                    "pending": False,
                    "stale": bool(stale),
                    "refreshing": bool(refreshing),
                    "source_age_ms": None if age is None else round(age * 1000.0, 1),
                    "stale_after_ms": round(3 * ttl * 1000.0),
                    "retry_after_ms": 100 if stale else None,
                    "last_refresh_error": admin_view.refresh_error(refresh_error, self._privileged()),
                    "incidents": admin_view.incidents(incidents.recent(4), self._privileged()),
                    "cache_contract": "gsd-dashboard-async-cache-2",
                })
                payload["dashboard_response"] = response_meta
                self._json(payload, 404 if "error" in payload else 200)
                return

            clock = dashboard_timing.RequestClock(path)
            if not dashboard_db_slots.acquire(timeout=dashboard_limit.SLOT_WAIT_SECONDS):
                clock.mark("slot_wait")
                clock.finish("capacity_busy")
                self._json(dict(dashboard_limit.BUSY), 503)
                return
            clock.mark("slot_wait")
            repo = None
            try:
                try:
                    repo = Repo(db_path)
                    clock.mark("repo_open")
                except DatabaseOperationalError as exc:
                    if exc.transient:
                        self._json({
                            "error": "database busy; dashboard will retry",
                            "retryable": True, "sqlstate": exc.sqlstate,
                        }, 503)
                        return
                    _log_database_unavailable(exc)
                    self._json({
                        "error": "database unavailable",
                        "detail": str(exc).splitlines()[0][:200],
                        "retryable": True,
                    }, 503)
                    return
                if parts[:2] == ["api", "campaigns"] and len(parts) > 2:
                    self._json(*campaign_manager.read(repo, parts[2:], dashboard_cache_root))
                elif parts[:2] == ["api", "campaigns"]:
                    rows = repo.conn.execute(
                        "SELECT campaign_id,status,created_utc,spec_json FROM campaigns ORDER BY created_utc"
                    ).fetchall()
                    payload = []
                    for row in rows:
                        spec = json.loads(row["spec_json"])
                        link = repo.campaign_link(row["campaign_id"])
                        payload.append({"campaign_id": row["campaign_id"], "status": row["status"],
                                        "created_utc": row["created_utc"],
                                        "mode": spec.get("mode", "bounded"),
                                        "name": spec.get("name"),
                                        "parent_campaign_id": link and link["parent_campaign_id"],
                                        "channel": link and link["channel"],
                                        })
                    self._json(payload)
                elif ((parts[:2] == ["api", "candidate"] and len(parts) == 3)
                      or (parts[:2] == ["api", "campaign"] and len(parts) == 5
                          and parts[3] == "candidate")):
                    scoped_candidate_path = (parts[:2] == ["api", "campaign"] and len(parts) == 5)
                    candidate_id = parts[4] if scoped_candidate_path else parts[2]
                    if scoped_candidate_path:
                        campaign_id = parts[2]
                    else:
                        query = parse_qs(urlparse(self.path).query)
                        campaign_id = (query.get("campaign") or [None])[0]
                    candidate = repo.candidate(candidate_id, campaign_id)
                    memberships = []
                    if not candidate:
                        memberships = repo.candidate_campaign_ids(candidate_id)
                        if len(memberships) == 1:
                            candidate = repo.candidate(candidate_id, memberships[0])
                        elif len(memberships) > 1:
                            self._json({"error": "candidate belongs to multiple campaigns",
                                        "campaigns": memberships}, 409)
                            return
                    if not candidate:
                        self._json({"error": "unknown candidate"}, 404)
                        return
                    campaign_id = candidate["campaign_id"]
                    campaign_row = repo.campaign(campaign_id) or {"spec": {}}
                    version = campaign_row["spec"].get("analysis_version") or ANALYSIS_VERSION
                    campaign_policy = campaign_row["spec"].get("policy", {})
                    phenotype_row = repo.base_block_phenotype(candidate_id, version, campaign_id)
                    locality_audit_row = repo.locality_audit_result(candidate_id, version, campaign_id)
                    measurement_rows = repo.measurements(candidate_id, version, campaign_id)
                    rung_rows = repo.rung_summaries(candidate_id, version, campaign_id)
                    compute_rows = repo.candidate_rung_compute(campaign_id, candidate_id)
                    compute_by_n = {row["n"]: row for row in compute_rows}
                    audit_rows = repo.evidence_audits(candidate_id, campaign_id)
                    audit_by_artifact = {row["artifact_hash"]: row for row in audit_rows}
                    audit_counts: dict[str, int] = {}
                    for audit in audit_rows:
                        audit_counts[audit["status"]] = audit_counts.get(audit["status"], 0) + 1
                    rung_payload = [public_row(row, "summary_json") |
                                    {"channels": _published_channels(row["summary"]),
                                     "compute": compute_by_n.get(row["n"], {
                                        "n": row["n"], "jobs": 0, "attempts": 0,
                                        "core_seconds": 0.0, "successful_seconds": 0.0,
                                        "failed_seconds": 0.0, "max_attempt_seconds": None,
                                        "cumulative_core_seconds": 0.0})}
                                    for row in rung_rows]
                    ladder = campaign_row["spec"].get("ladder") or []
                    lineage = None
                    depth = campaign_row["spec"].get("depth_continuation") or {}
                    source_id = str(depth.get("source_campaign_id") or "") or None
                    if source_id and source_id != str(campaign_id):
                        source_rows = repo.rung_summaries(candidate_id, version, source_id)
                        if source_rows:
                            source_campaign = repo.campaign(source_id) or {"spec": {}}
                            lineage = {
                                "source_campaign_id": source_id,
                                "anchor_n": depth.get("anchor_n"),
                                "source_ensemble_code": _ensemble_code_for(repo, source_id, candidate_id),
                                "source_ladder": (source_campaign["spec"].get("ladder") or []),
                                "score_scope": (
                                    "the stability score on this page is computed from this "
                                    "campaign's rungs only; the rungs below were measured under "
                                    "the source campaign's frozen spec and do not enter it"),
                                "rungs": [public_row(row, "summary_json") |
                                          {"channels": _published_channels(row["summary"])}
                                          for row in source_rows],
                            }
                    measured_ns = {row["n"] for row in rung_rows}
                    next_n = next((int(n) for n in ladder if int(n) not in measured_ns), None)
                    next_estimate = None
                    if next_n is not None:
                        profile = observed_profile(
                            repo.conn, campaign_id=campaign_id,
                            candidate_id=candidate_id,
                        )
                        if len(profile) < 2:
                            profile = observed_profile(
                                repo.conn, campaign_id=campaign_id,
                                nonterminal_only=True,
                            )
                        analysis_profile = observed_analysis_profile(repo.conn)
                        simulation_per_job = predict_wall(profile, next_n)
                        analysis_per_job = predict_wall(analysis_profile, next_n)
                        total_per_job = (
                            None if simulation_per_job is None
                            else float(simulation_per_job)
                            + (float(analysis_per_job) if analysis_per_job is not None else 0.0)
                        )
                        index = ladder.index(next_n) if next_n in ladder else 0
                        stage = campaign_row["spec"].get("stage_seeds") or {}
                        seeds = int(stage.get(str(index), campaign_row["spec"].get("default_seeds", 2)))
                        next_estimate = {
                            "n": next_n, "seeds": seeds,
                            "per_job_seconds": (None if total_per_job is None
                                                else round(total_per_job, 3)),
                            "simulation_per_job_seconds": (None if simulation_per_job is None
                                                           else round(simulation_per_job, 3)),
                            "analysis_per_job_seconds": (None if analysis_per_job is None
                                                         else round(analysis_per_job, 3)),
                            "analysis_priced": analysis_per_job is not None,
                            "rung_core_seconds": (None if total_per_job is None
                                                  else round(total_per_job * seeds, 3)),
                        }
                    candidate_jobs = repo.jobs(campaign_id, candidate_id=candidate_id)
                    execution_history = []
                    for job in candidate_jobs:
                        execution_history.append({
                            key: job.get(key) for key in (
                                "job_id", "campaign_id", "candidate_id", "kind", "stage", "n", "seed",
                                "replicate", "priority", "sealed", "requested_by", "status", "attempts",
                                "created_utc", "updated_utc", "result_artifact", "error"
                            )
                        } | {"spec": job.get("spec") or {}})
                    state_history = repo.candidate_state_history(campaign_id, candidate_id)
                    attempt_history = [dict(row) for row in repo.conn.execute(
                        "SELECT a.attempt_id,a.job_id,a.number,a.worker,a.started_utc,a.finished_utc,"
                        "a.exit_code,a.peak_rss_bytes,a.wall_seconds,a.error,a.resource_json,j.n,j.seed,j.stage "
                        "FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
                        "WHERE j.campaign_id=? AND j.candidate_id=? ORDER BY a.started_utc,a.attempt_id",
                        (campaign_id, candidate_id),
                    ).fetchall()]
                    for row in attempt_history:
                        raw = row.pop("resource_json", None)
                        row["resource"] = json.loads(raw or "{}")
                    active_simulation = [row for row in execution_history
                                         if str(row.get("status")) in {"queued", "leased"}]
                    active_analysis = [dict(row) for row in repo.conn.execute(
                        "SELECT input_artifact,n,seed,status,lease_owner,priority,producer_job,"
                        "created_utc,updated_utc FROM analysis_queue WHERE campaign_id=? "
                        "AND candidate_id=? AND analysis_version=? AND status IN ('queued','leased') "
                        "ORDER BY priority,created_utc,input_artifact",
                        (campaign_id, candidate_id, version),
                    ).fetchall()]
                    active_work = {
                        "simulation": active_simulation,
                        "analysis": active_analysis,
                        "count": len(active_simulation) + len(active_analysis),
                    }
                    reproduction = {
                        "capsule_contract": "gsd-specimen-capsule-1",
                        "build_number": BUILD_NUMBER,
                        "runtime_fingerprint": runtime_fingerprint(),
                        "environment_fingerprint": environment_fingerprint(),
                        "engine_version": ENGINE_VERSION,
                        "analysis_version": version,
                        "policy_rule_version": RULE_VERSION,
                        "search_space_version": SEARCH_SPACE_VERSION,
                        "campaign": {
                            "campaign_id": campaign_id,
                            "search_seed": campaign_row.get("search_seed"),
                            "spec": campaign_row.get("spec") or {},
                            "campaign_role": campaign_row.get("campaign_role"),
                            "parent_campaign_id": campaign_row.get("parent_campaign_id"),
                            "campaign_series_id": campaign_row.get("campaign_series_id"),
                            "science_contract_hash": campaign_row.get("science_contract_hash"),
                            "search_policy_hash": campaign_row.get("search_policy_hash"),
                            "resource_policy_hash": campaign_row.get("resource_policy_hash"),
                            "experiment_config_hash": campaign_row.get("experiment_config_hash"),
                            "created_build": campaign_row.get("created_build"),
                            "created_runtime_fingerprint": campaign_row.get("created_runtime_fingerprint"),
                        },
                        "execution_history": execution_history,
                        "attempt_history": attempt_history,
                        "state_history": state_history,
                        "active_work_at_export": active_work,
                    }
                    self._json({
                        "campaign": {"mode": campaign_row["spec"].get("mode", "bounded"),
                                     "role": campaign_row.get("campaign_role") or campaign_row["spec"].get("campaign_role", "discovery"),
                                     "link": repo.campaign_link(campaign_id)},
                        "reproduction": reproduction,
                        "stability": _candidate_stability(
                            (phenotype_row or {}).get("phenotype"), campaign_row["spec"], rung_rows=rung_rows),
                        "active_work": active_work,
                        "equilibration": equilibration_rows(measurement_rows, campaign_policy),
                        "candidate": {k: candidate[k] for k in
                                      ("candidate_id", "campaign_id", "state", "state_reason",
                                       "dynamics", "complexity", "lineage_parent", "created_utc")}
                                     | {"spec": candidate["spec"], "law": law_label(candidate["spec"]),
                                        "regime": dsl.dynamics_regime(candidate["spec"]),
                                        "ensemble_code": _ensemble_code_for(
                                            repo, campaign_id, candidate_id),
                                        "candidate_number": candidate_number_for(repo, campaign_id, candidate_id),
                                        "fingerprint_verified":
                                            dsl.fingerprint(candidate["spec"]) == candidate["candidate_id"]},
                        "law_dynamics": law_dynamics_of(candidate["spec"]),
                        "rungs": rung_payload,
                        "lineage": lineage, "identity": identity_for(repo, campaign_id, candidate_id, candidate["spec"]),
                        "four_rung_phenotype": (phenotype_row or {}).get("phenotype"),
                        "locality_audit": (locality_audit_row or {}).get("result"),
                        "compute": {"rungs": compute_rows,
                                    "total_core_seconds": round(sum(r["core_seconds"] for r in compute_rows), 3),
                                    "next_rung_estimate": next_estimate},
                        "provenance": {"counts": audit_counts,
                                       "audits": [public_row(row, "detail_json") for row in audit_rows]},
                        "transitions": _transitions_from_rungs(rung_payload),
                        "engine_decisions": repo.engine_decisions(campaign_id, candidate_id),
                        "rung_diagnostics": repo.rung_diagnostics(campaign_id, candidate_id),
                        "proposal_assessments": [public_row(row, "assessment_json")
                                                 for row in repo.proposal_assessments(campaign_id, candidate_id)],
                        "measurements": [{"n": m["n"],
                                          "seed": m["seed"],
                                          "sealed": False,
                                          "input_artifact": m["input_artifact"],
                                          "provenance": (audit_by_artifact.get(m["input_artifact"]) or {}).get("status", "not-audited"),
                                          "metrics": m["metrics"],
                                          "curves_artifact": m["curves_artifact"]}
                                         for m in measurement_rows]})
                else:
                    self._json({"error": "not found"}, 404)
            except CLIENT_DISCONNECTS:
                return
            except Exception as exc:
                request_id = uuid.uuid4().hex[:12]
                console_error(
                    "api",
                    f"{request_id}: {type(exc).__name__}: {exc}\n"
                    + traceback.format_exc(limit=16),
                )
                self._json({"error": "internal server error", "request_id": request_id}, 500)
            finally:
                if repo is not None:
                    repo.close()
                dashboard_db_slots.release()
                clock.finish()
    return Handler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, max_request_threads: int = 64, **kwargs):
        if max_request_threads < 1:
            raise ValueError("max_request_threads must be positive")
        self._request_slots = threading.BoundedSemaphore(max_request_threads)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        self._request_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def _dashboard_admin_token() -> str:
    capability_file = os.environ.get("GSD_DASHBOARD_ADMIN_FILE", "").strip()
    if capability_file:
        text = Path(capability_file).read_text(encoding="utf-8").strip()
        token = (parse_qs(urlparse(text).fragment).get("admin") or [""])[0].strip()
        if not token:
            raise RuntimeError("dashboard admin capability file has no #admin token")
        return token
    return (os.environ.get("GSD_DASHBOARD_ADMIN_TOKEN", "").strip()
            or secrets.token_urlsafe(24))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--blobs", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="API listener; fleet mode binds this to loopback")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--base-path", default="")
    parser.add_argument("--max-request-threads", type=int, default=16)
    parser.add_argument("--exploration-map-mode", choices=DASHBOARD_HEAVY_SECTION_MODES, default="off")
    parser.add_argument("--past-research-mode", choices=DASHBOARD_HEAVY_SECTION_MODES, default="off")
    parser.add_argument("--report-campaign")
    parser.add_argument("--report-root")
    parser.add_argument("--internal-token-file")
    parser.add_argument("--snapshot-tmp")
    args = parser.parse_args(argv)
    admin_token = _dashboard_admin_token()
    internal_token = ""
    if args.internal_token_file:
        internal_token = Path(args.internal_token_file).read_text(encoding="utf-8").strip()
        if not internal_token:
            raise RuntimeError("internal API capability file is empty")

    report_campaign_id = str(args.report_campaign) if args.report_campaign else None
    if report_campaign_id is None:
        try:
            with Repo(args.db) as repo:
                report_campaign_id = campaign_control.reporting_focus(repo)
        except Exception as exc:
            console_error("api", f"report campaign lookup failed: {type(exc).__name__}: {exc}")
    try:
        with Repo(args.db) as repo:
            campaign_manager.warm_aggregates(repo.db_target)
            if quiet_report.in_progress(repo):
                quiet_report.ensure_runner(lambda: Repo(args.db))
    except Exception as exc:
        console_error("api", f"quiet report recovery check failed: {type(exc).__name__}: {exc}")
    report_root = (Path(args.report_root).resolve() if args.report_root else
                   (Path(args.blobs).resolve().parent / "reports" / f"live_campaign_{report_campaign_id}"
                    if report_campaign_id is not None else None))

    server = BoundedThreadingHTTPServer(
        (args.bind, args.port),
        build_handler(
            args.db, args.blobs, admin_token, args.port,
            bind_host=args.bind, allowed_hosts=tuple(args.allow_host),
            base_path=args.base_path,
            exploration_map_mode=args.exploration_map_mode, past_research_mode=args.past_research_mode,
            report_root=report_root, report_campaign_id=report_campaign_id,
            internal_token=internal_token, snapshot_tmp=args.snapshot_tmp,
        ),
        max_request_threads=args.max_request_threads,
    )
    print(f"{iso_utc_now()} [api] API control plane listening on {args.bind}:{args.port}; resident dashboard path uses bounded SQL summaries")
    print(f"{iso_utc_now()} [api] report generation is out of process and on request only; a cycle runs only while no work is in flight")
    if report_campaign_id is not None:
        print(f"{iso_utc_now()} [api] report control campaign {report_campaign_id}; live immutable snapshot capability {'active' if internal_token else 'disabled'}")
    print(f"{iso_utc_now()} [api] local admin capability active; secret intentionally not printed")

    _sidecar_at_start = _published_sidecar_reading()
    print(f"{iso_utc_now()} [api] cpu power: {_power_sidecar.describe_reading(_sidecar_at_start)}")

    start_heartbeat_thread("api", args.db, detail=lambda: {
        "bind": f"{args.bind}:{args.port}",
        "request_threads": args.max_request_threads,
        "host_snapshot_age_seconds": round(max(0.0, time.monotonic() - _HOST_SNAPSHOT["at"]), 1),
    })

    interrupted_by: int | None = None
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _interrupt(signum, frame):
        nonlocal interrupted_by
        interrupted_by = signum
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGINT, _interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_btop_sidecar()
        server.server_close()
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
    if interrupted_by == signal.SIGINT:
        return 130
    if interrupted_by == signal.SIGTERM:
        return 143
    return 0


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
