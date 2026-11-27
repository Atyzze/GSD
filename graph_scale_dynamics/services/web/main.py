from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import mimetypes
import os
import sys
import threading
from importlib.resources import files as resource_files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from graph_scale_dynamics.operations.dev_mode import enabled as dev_mode_enabled
from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
from graph_scale_dynamics.operations.report_home import base_of, current_root
from graph_scale_dynamics.reporting.study_bundle import STUDY_DIR, bundles_dir, read_index as read_study_index
from graph_scale_dynamics.services.web import streaming
from graph_scale_dynamics.services.web.bundle_keeper import AccessCounter, BundleKeeper

LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1", ""})
CLIENT_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
ADMIN_TOKEN_HEADER = "X-GSD-Admin-Token"
GENERIC_FAULT = "internal server error"

SPA_SHELL_PATHS = frozenset({
    "/", "/index.html", "/home", "/map", "/explorer", "/reports", "/calibration", "/campaigns", "/system",
})


class RuntimeImportHeartbeat:
    def __init__(self, api_host: str, api_port: int, token_file: str | None,
                 *, interval_seconds: float = 60.0) -> None:
        self._api_host, self._api_port = api_host, int(api_port)
        self._token = None
        if token_file:
            try:
                from graph_scale_dynamics.operations.internal_api import read_internal_token
                self._token = read_internal_token(token_file)
            except Exception:
                self._token = None
        self._interval = float(interval_seconds)
        self._digest: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gsd-web-runtime-imports", daemon=True)

    def start(self) -> None:
        if self._token:
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def publish_once(self) -> bool:
        from graph_scale_dynamics.observability.evidence_sources import (
            runtime_import_digest, runtime_import_snapshot,
        )
        names = runtime_import_snapshot()
        digest = runtime_import_digest(names)
        if digest == self._digest:
            return False
        body = json.dumps({"modules": names}).encode("utf-8")
        conn = http.client.HTTPConnection(self._api_host, self._api_port, timeout=5.0)
        try:
            conn.request("POST", "/internal/runtime-imports/web", body=body,
                         headers={"Content-Type": "application/json",
                                  "X-GSD-Internal-Token": self._token or ""})
            response = conn.getresponse()
            response.read()
            if response.status != 200:
                return False
        finally:
            conn.close()
        self._digest = digest
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.publish_once()
            except Exception:
                pass
            self._stop.wait(self._interval)


SLOW_ROUTES = (("/api/memory-ledger", 20.0), ("/api/runtime-imports", 10.0),
               ("/api/campaign/", 10.0), ("/api/candidate/", 10.0),
               ("/api/structure/", 10.0), ("/api/curves/", 10.0), ("/api/reports/", 10.0),
               ("/api/focus", 10.0), ("/api/campaigns/overview", 30.0), ("/api/study-hours/", 10.0))

WRITE_TIMEOUT_SECONDS = 300.0
READ_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_REQUEST_BYTES = 1_000_000
SOCKET_TIMEOUT_SECONDS = 60.0
MAX_CONCURRENT_REQUESTS = 64
KEEPALIVE_IDLE_SECONDS = 5.0


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

    def process_request(self, request, client_address):
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def normalize_base_path(value: str) -> str:
    value = str(value or "").strip()
    if not value or value == "/":
        return ""
    return "/" + value.strip("/")


def build_handler(*, api_host: str, api_port: int, bind_host: str,
                  allowed_hosts: tuple[str, ...], base_path: str,
                  report_root: Path | None, access_counter: AccessCounter | None = None):
    base_path = normalize_base_path(base_path)
    launch_root = report_root.resolve() if report_root else None
    access_counter = access_counter or AccessCounter()

    class _FollowingRoot:
        def __truediv__(self, other):
            return current_root(launch_root) / other

        def __bool__(self):
            return launch_root is not None

        def resolve(self):
            return current_root(launch_root)

        def __fspath__(self):
            return str(current_root(launch_root))

        def __str__(self):
            return str(current_root(launch_root))

    report_root = _FollowingRoot() if launch_root is not None else None
    large = streaming.LargeBodies()
    api_timeout_seconds = max(0.25, float(os.environ.get("GSD_WEB_API_TIMEOUT_SECONDS", "1.5")))

    def timeout_for(path: str, method: str = "GET") -> float:
        if str(method).upper() not in READ_METHODS:
            return max(api_timeout_seconds, WRITE_TIMEOUT_SECONDS)
        route = urlparse(path).path
        return max(api_timeout_seconds, next((t for prefix, t in SLOW_ROUTES if route.startswith(prefix)), 0.0))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            self._requests_served = 0

        def handle_one_request(self):
            if self._requests_served:
                self.connection.settimeout(KEEPALIVE_IDLE_SECONDS)
            self._requests_served += 1
            super().handle_one_request()

        def parse_request(self):
            self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            return super().parse_request()

        def log_message(self, *args):
            pass

        def _allowed_hostname(self, hostname: str) -> bool:
            hostname = (hostname or "").strip().lower().rstrip(".")
            allowed = {str(host).strip().lower().rstrip(".") for host in allowed_hosts}
            if hostname in LOOPBACK_HOSTNAMES or hostname in allowed:
                return True
            if bind_host not in ("0.0.0.0", "::", "") and hostname == bind_host.lower():
                return True
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return False
            return bool(address.is_loopback or address.is_private or address.is_link_local)

        def _hostname(self) -> str:
            host = (self.headers.get("Host") or "").strip().lower()
            if host.startswith("[") and "]" in host:
                return host[1:host.index("]")]
            return host.rsplit(":", 1)[0] if host.count(":") == 1 else host

        def _path(self) -> str:
            path = urlparse(self.path).path
            if base_path and (path == base_path or path.startswith(base_path + "/")):
                path = path[len(base_path):] or "/"
            return path

        def _send(self, body: bytes, content_type: str, code: int = 200,
                  *, cache_control: str = "no-store",
                  extra_headers: dict | None = None) -> None:
            try:
                streaming.send_head(self, code, content_type, len(body), cache_control=cache_control,
                                    extra_headers=extra_headers)
                self.wfile.write(body)
            except CLIENT_DISCONNECTS:
                self.close_connection = True

        def _browser_origin(self) -> str | None:
            origin = (self.headers.get("Origin") or "").strip()
            if origin and origin.lower() != "null":
                return origin
            if origin.lower() == "null":
                return "null"
            referer = (self.headers.get("Referer") or "").strip()
            if referer:
                parsed = urlparse(referer)
                return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "null"
            return None

        def _host_port(self) -> int | None:
            host = (self.headers.get("Host") or "").strip()
            tail = host.rsplit("]", 1)[-1] if host.startswith("[") else (host if host.count(":") == 1 else "")
            _, colon, port = tail.rpartition(":")
            return int(port) if colon and port.isdigit() else None

        def _same_origin(self, origin: str) -> bool:
            parsed = urlparse(origin)
            hostname = (parsed.hostname or "").lower()
            if (parsed.scheme not in ("http", "https") or hostname != self._hostname()
                    or not self._allowed_hostname(hostname)):
                return False
            try:
                origin_port = parsed.port
            except ValueError:
                return False
            default = 443 if parsed.scheme == "https" else 80
            host_port = self._host_port()
            if host_port is None:
                return origin_port in (None, default)
            return (origin_port if origin_port is not None else default) == host_port

        def _write_refused(self) -> bool:
            if str(self.command).upper() in READ_METHODS:
                return False
            origin = self._browser_origin()
            if origin is None or self._same_origin(origin):
                return False
            self._send(json.dumps({"error": "origin not allowed: a write must come from this dashboard's own page",
                                   "origin": origin}).encode(), "application/json; charset=utf-8", 403)
            return True

        def _proxy(self, upstream_override: str | None = None) -> None:
            body = (getattr(self, "_body", b"") or None) if str(self.command).upper() not in READ_METHODS else None
            headers = {}
            for key in ("Content-Type", ADMIN_TOKEN_HEADER):
                if self.headers.get(key):
                    headers[key] = self.headers[key]
            headers["Host"] = f"{api_host}:{api_port}"
            origin = self._browser_origin()
            if origin is not None and self._same_origin(origin):
                headers["Origin"] = f"http://{api_host}:{api_port}"
            if upstream_override is not None:
                upstream_path = upstream_override
            else:
                upstream_path = self.path
                if base_path:
                    parsed = urlparse(self.path)
                    route = self._path()
                    upstream_path = route + (("?" + parsed.query) if parsed.query else "")
            conn = http.client.HTTPConnection(api_host, api_port, timeout=timeout_for(upstream_path, self.command))
            sent = False
            try:
                conn.request(self.command, upstream_path, body=body, headers=headers)
                sent = True
                response = conn.getresponse()
                streaming.relay(self, large, response, scrub=(
                    (lambda payload: (_without_detail(payload, upstream_path, response.status), streaming.JSON))
                    if response.status >= 500 and not self.headers.get(ADMIN_TOKEN_HEADER) else None))
            except (OSError, http.client.HTTPException) as exc:
                if sent and str(self.command).upper() not in READ_METHODS:
                    self._send(json.dumps({
                        "error": "outcome unknown: the API did not answer in time; reload to see whether it happened "
                                 "before trying again", "detail": type(exc).__name__, "retryable": False,
                    }).encode(), "application/json; charset=utf-8", 504)
                else:
                    self._send(json.dumps({
                        "error": "api temporarily unavailable", "detail": type(exc).__name__,
                        "retryable": True,
                    }).encode(), "application/json; charset=utf-8", 503)
            finally:
                conn.close()

        def _render_ui_resource(self, name: str) -> bytes:
            home = (base_path or "/")
            if not home.endswith("/"):
                home += "/"
            text = resource_files("graph_scale_dynamics.resources").joinpath("ui", name).read_text(encoding="utf-8")
            return text.replace("__GSD_BASE_PATH_JSON__", json.dumps(base_path)).replace(
                "__GSD_BUILD_NUMBER__", str(BUILD_NUMBER)
            ).replace("__GSD_RUNTIME_FINGERPRINT__", runtime_fingerprint()).replace(
                "__GSD_RUNTIME_SHORT__", runtime_fingerprint()[:8]
            ).replace("__GSD_HOME_HREF__", home).replace(
                "__GSD_DEV_MODE__", "true" if dev_mode_enabled() else "false"
            ).encode()

        def _serve_index(self) -> None:
            self._send(self._render_ui_resource("index.html"), "text/html; charset=utf-8")

        def _serve_ui_page(self, name: str) -> None:
            self._send(self._render_ui_resource(name), "text/html; charset=utf-8")

        def _serve_ui_asset(self, name: str, content_type: str) -> None:
            try:
                body = resource_files("graph_scale_dynamics.resources").joinpath("ui", name).read_bytes()
            except (FileNotFoundError, OSError):
                self._send(b'{"error":"not found"}', "application/json", 404)
                return
            self._send(body, content_type, 200, cache_control="no-store")

        def _serve_report(self, path: str) -> None:
            if report_root is None:
                self._send(b'{"error":"reports unavailable"}', "application/json", 404)
                return
            relative = path[len("/reports"):].lstrip("/") or "index.html"
            served_root = report_root.resolve()
            target = (served_root / relative).resolve()
            try:
                target.relative_to(served_root)
            except ValueError:
                self._send(b'{"error":"not found"}', "application/json", 404)
                return
            if not target.is_file():
                self._send(b'{"error":"report file not ready"}', "application/json", 404)
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            streaming.serve_file(self, large, target, content_type)

        def _serve_study(self, path: str) -> None:
            if launch_root is None:
                self._send(b'{"error":"reports unavailable"}', "application/json", 404)
                return
            base = base_of(launch_root)
            if path in ("/api/reports/study", "/reports/study", "/reports/study/"):
                index = read_study_index(base)
                index["download_prefix"] = f"/reports/{STUDY_DIR}/bundles/"
                self._send(json.dumps(index, sort_keys=True).encode(), "application/json; charset=utf-8")
                return
            served_root = (base / STUDY_DIR).resolve()
            target = (served_root / path[len(f"/reports/{STUDY_DIR}/"):]).resolve()
            try:
                target.relative_to(served_root)
            except ValueError:
                self._send(b'{"error":"not found"}', "application/json", 404)
                return
            if not target.is_file() or target.parent != bundles_dir(base).resolve():
                self._send(b'{"error":"not found"}', "application/json", 404)
                return
            content_type, extra = mimetypes.guess_type(str(target))[0] or "application/octet-stream", None
            if target.suffix == ".zst":
                content_type = "application/zstd"
                extra = {"Content-Disposition": f'attachment; filename="{target.name}"'}
            elif target.suffix == ".svg":
                content_type = "image/svg+xml"
            streaming.serve_file(self, large, target, content_type, extra_headers=extra)

        def _dispatch(self):
            if not self._allowed_hostname(self._hostname()):
                self._send(b'{"error":"host not allowed"}', "application/json", 403)
                return
            if self._write_refused():
                return
            path = self._path()
            if path in SPA_SHELL_PATHS:
                self._serve_index()
            elif path in ("/candidate", "/candidate.html"):
                self._serve_ui_page("candidate.html")
            elif path == "/assets/system.css":
                self._serve_ui_asset("system.css", "text/css; charset=utf-8")
            elif path == "/assets/system.js":
                self._serve_ui_asset("system.js", "text/javascript; charset=utf-8")
            elif path == "/assets/app.js":
                self._serve_ui_asset("app.js", "text/javascript; charset=utf-8")
            elif path == "/assets/term_visual.js":
                self._serve_ui_asset("term_visual.js", "text/javascript; charset=utf-8")
            elif path in ("/assets/map.js", "/assets/selection.js"):
                self._serve_ui_asset(path.rsplit("/", 1)[1], "text/javascript; charset=utf-8")
            elif path.startswith("/candidate-data/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                parts = [p for p in path.split("/") if p]
                if len(parts) == 3 and parts[0] == "candidate-data":
                    self._proxy(f"/api/campaign/{parts[1]}/candidate/{parts[2]}")
                elif len(parts) == 2 and parts[0] == "candidate-data":
                    self._proxy(f"/api/candidate/{parts[1]}")
                else:
                    self._send(b'{"error":"not found"}', "application/json", 404)
            elif path.startswith("/structure-data/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                parts = [p for p in path.split("/") if p]
                if len(parts) == 3:
                    self._proxy(f"/api/structure/{parts[1]}/{parts[2]}")
                else:
                    self._send(b'{"error":"not found"}', "application/json", 404)
            elif path.startswith("/curves-data/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                parts = [p for p in path.split("/") if p]
                if len(parts) == 4 and parts[3].isdigit():
                    self._proxy(f"/api/curves/{parts[1]}/{parts[2]}/{parts[3]}")
                else:
                    self._send(b'{"error":"not found"}', "application/json", 404)
            elif path in ("/api/reports/study", "/reports/study") or path.startswith("/reports/study/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                self._serve_study(path)
            elif path == "/reports" or path.startswith("/reports/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                self._serve_report(path)
            elif path == "/api" or path.startswith("/api/"):
                access_counter.record(path, self.headers.get("Referer"), self.headers.get("X-GSD-Page"))
                self._proxy()
            else:
                self._send(b'{"error":"not found"}', "application/json", 404)

        def _answering(self, answer=None) -> None:
            try:
                read, self._body = streaming.read_request_body(self, MAX_REQUEST_BYTES)
                if read:
                    (answer or self._dispatch)()
            except (ValueError, UnicodeError) as exc:
                try:
                    self._send(json.dumps({"error": "malformed request", "detail": type(exc).__name__}).encode(),
                               "application/json; charset=utf-8", 400)
                except OSError:
                    pass

        def do_GET(self):
            self._answering()

        def do_POST(self):
            self._answering()

        def do_OPTIONS(self):
            self._answering(lambda: self._send(json.dumps({"error": "method not allowed"}).encode(),
                                               "application/json; charset=utf-8", 405,
                                               extra_headers={"Allow": "GET, POST"}))

    return Handler


def _without_detail(payload: bytes, path: str, status: int = 500) -> bytes:
    try:
        found = json.loads(payload or b"{}")
    except ValueError:
        found = {}
    found = found if isinstance(found, dict) else {}
    if status != 500 and found:
        return json.dumps({key: value for key, value in found.items() if key != "detail"}).encode()
    if found.get("error") != GENERIC_FAULT:
        print(f"web: a {status} from {path} shown without its detail to a viewer without the admin token: "
              f"{str(found.get('error') or payload[:300])[:300]}", file=sys.stderr, flush=True)
    kept = {key: found[key] for key in ("request_id", "retryable") if key in found}
    return json.dumps({"error": GENERIC_FAULT, **kept}).encode()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--base-path", default="")
    parser.add_argument("--reports")
    parser.add_argument("--internal-token-file", default=None,
                        help="loopback capability for handing this process's import set to the API")
    args = parser.parse_args(argv)
    counter = AccessCounter()
    keeper = None
    if args.reports:
        keeper = BundleKeeper(Path(args.reports), counter)
        keeper.start()
    heartbeat = RuntimeImportHeartbeat(args.api_host, args.api_port, args.internal_token_file)
    heartbeat.start()
    server = BoundedThreadingHTTPServer(
        (args.bind, args.port),
        build_handler(api_host=args.api_host, api_port=args.api_port, bind_host=args.bind,
                      allowed_hosts=tuple(args.allow_host), base_path=args.base_path,
                      report_root=Path(args.reports) if args.reports else None,
                      access_counter=counter),
    )
    print(f"[web] dashboard shell listening on {args.bind}:{args.port}; API upstream 127.0.0.1:{args.api_port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        heartbeat.stop()
        if keeper is not None:
            keeper.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
