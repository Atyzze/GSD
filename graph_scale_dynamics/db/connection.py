from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

from graph_scale_dynamics import PROJECT_ROOT

POSTGRES_SCHEMES = ("postgresql://", "postgres://")
WORK_CHANNEL = "gsd_work"
LOCAL_POSTGRES_ENV = PROJECT_ROOT / ".env.postgres"
POSTGRES_INSTANCE_HELPER = PROJECT_ROOT / "tools" / "postgres_instance.py"
INTERNAL_POSTGRES_READY = "GSD_INTERNAL_POSTGRES_READY"
_POSTGRES_ENSURED = False

def _read_local_postgres_env() -> dict[str, str]:
    if not LOCAL_POSTGRES_ENV.is_file():
        return {}
    if os.name == "posix" and LOCAL_POSTGRES_ENV.stat().st_mode & 0o077:
        raise ValueError(
            f"refusing PostgreSQL credential file with group/world permissions: "
            f"{LOCAL_POSTGRES_ENV}; run chmod 600 {LOCAL_POSTGRES_ENV}"
        )
    values: dict[str, str] = {}
    for raw in LOCAL_POSTGRES_ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _database_url_from_env_file() -> str | None:
    values = _read_local_postgres_env()
    if not values:
        return None
    instance = values.get("INSTANCE_NAME", "").strip()
    if not instance:
        raise ValueError(
            f"{LOCAL_POSTGRES_ENV} is not a current managed PostgreSQL config; "
            "run `python tools/postgres_instance.py ensure` to upgrade it"
        )
    required = ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_SOCKET")
    missing = [key for key in required if not values.get(key, "").strip()]
    if missing:
        raise ValueError(
            f"incomplete PostgreSQL credential file {LOCAL_POSTGRES_ENV}; missing "
            + ", ".join(missing)
        )
    user = values["POSTGRES_USER"]
    database = values["POSTGRES_DB"]
    password = values["POSTGRES_PASSWORD"]
    socket_path = Path(values["POSTGRES_SOCKET"]).expanduser().resolve()
    try:
        socket_path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            f"POSTGRES_SOCKET in {LOCAL_POSTGRES_ENV} escapes the project root: {socket_path}"
        ) from exc
    query = urlencode({"host": str(socket_path)})
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@/"
        f"{quote(database, safe='')}?{query}"
    )


def _ensure_folder_postgres() -> None:
    global _POSTGRES_ENSURED
    if _POSTGRES_ENSURED or os.environ.get(INTERNAL_POSTGRES_READY) == "1":
        _POSTGRES_ENSURED = True
        return
    if not POSTGRES_INSTANCE_HELPER.is_file():
        raise ValueError(
            f"cannot bootstrap folder-local PostgreSQL: missing {POSTGRES_INSTANCE_HELPER}"
        )
    print(
        f"[database] ensuring rootless folder-local PostgreSQL for {PROJECT_ROOT}",
        file=sys.stderr, flush=True,
    )
    completed = subprocess.run(
        [sys.executable, str(POSTGRES_INSTANCE_HELPER), "ensure"],
        cwd=PROJECT_ROOT,
    )
    if completed.returncode != 0:
        raise ValueError(
            "automatic folder-local PostgreSQL bootstrap failed. The application "
            "does not use sudo, host PostgreSQL, Docker/Podman daemons, external "
            "database credentials, or user-global state. It requires the bundled "
            "unprivileged namespace runtime and its pinned PostgreSQL OCI payload."
        )
    _POSTGRES_ENSURED = True
    os.environ[INTERNAL_POSTGRES_READY] = "1"


class DatabaseOperationalError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False,
                 sqlstate: str | None = None, outcome_unknown: bool = False):
        super().__init__(message)
        self.transient = bool(transient)
        self.sqlstate = sqlstate
        self.outcome_unknown = bool(outcome_unknown)


class SessionLockLost(SystemExit):
    pass


_SAFE_TO_REPEAT = re.compile(r"\s*(SELECT|SHOW|SET|LISTEN|UNLISTEN|VALUES|EXPLAIN|BEGIN|START\s+TRANSACTION)\b",
                             re.IGNORECASE)


def safe_to_repeat(sql: str) -> bool:
    return bool(_SAFE_TO_REPEAT.match(str(sql)))


def _validated_schema_name(schema: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"unsafe PostgreSQL schema name: {schema!r}")
    return schema


def _schema_dsn_from_resolved(resolved: str, schema: str) -> str:
    schema = _validated_schema_name(schema)
    parts = urlsplit(resolved)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    options = query.get("options", "").strip()
    query["options"] = (options + f" -csearch_path={schema}").strip()
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def _search_path_schema(value: str) -> str | None:
    query = dict(parse_qsl(urlsplit(value).query, keep_blank_values=True))
    options = query.get("options", "")
    match = re.search(r"(?:^|\s)-csearch_path=([A-Za-z_][A-Za-z0-9_]*)(?:\s|$)", options)
    return match.group(1) if match else None


def resolve_target(target: str | Path | None = None, *, auto_provision: bool = True) -> str:
    raw = "folder" if target is None else str(target)
    schema = None
    if raw.startswith("folder-schema:"):
        schema = _validated_schema_name(raw.split(":", 1)[1])
        raw = "folder"
    if raw in {"", "folder", "local"}:
        if auto_provision:
            _ensure_folder_postgres()
        local = _database_url_from_env_file()
        if local is None:
            raise ValueError(
                "folder-local PostgreSQL is not configured yet; the first runtime "
                "command will create/start it rootlessly"
            )
        raw = local
    elif raw.startswith("env:"):
        name = raw[4:]
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"PostgreSQL runtime requires {name}")
        raw = value
    if not raw.lower().startswith(POSTGRES_SCHEMES):
        raise ValueError(
            "Graph Scale Dynamics is PostgreSQL-only; expected 'folder', "
            "'folder-schema:NAME', or a deliberate postgresql:// recovery URL"
        )
    return _schema_dsn_from_resolved(raw, schema) if schema else raw


def service_database_reference(target: str | Path | None = None) -> str:
    resolved = resolve_target(target)
    folder = _database_url_from_env_file()
    if folder is not None and _dsn_identity(resolved) == _dsn_identity(folder):
        schema = _search_path_schema(resolved)
        return f"folder-schema:{schema}" if schema else "folder"
    return resolved


def _dsn_identity(value: str) -> tuple[str, str | None, str | None, str | None, int | None, str, str | None]:
    parts = urlsplit(value)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    return (
        parts.scheme.lower(), parts.username, parts.password, parts.hostname,
        parts.port, parts.path, query.get("host"),
    )


def display_target(target: str | Path | None = None, *, auto_provision: bool = True) -> str:
    raw = resolve_target(target, auto_provision=auto_provision)
    parts = urlparse(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    socket_host = query.get("host", "")
    database = parts.path.lstrip("/") or "postgres"
    user = f"{parts.username}@" if parts.username else ""
    if socket_host.startswith("/"):
        return f"postgresql://{user}unix:{socket_host}/{database}"
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    return f"postgresql://{user}{host}{port}/{database}"


def postgres_schema_dsn(target: str | Path, schema: str) -> str:
    return _schema_dsn_from_resolved(resolve_target(target), schema)

def _qmark_to_format(sql: str) -> str:
    out: list[str] = []
    state = "normal"
    dollar_tag: str | None = None
    block_depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]

        if ch == "%":
            out.append("%%")
            i += 1
            continue

        if state == "line_comment":
            out.append(ch)
            i += 1
            if ch == "\n":
                state = "normal"
            continue

        if state == "block_comment":
            if sql.startswith("/*", i):
                out.append("/*")
                block_depth += 1
                i += 2
            elif sql.startswith("*/", i):
                out.append("*/")
                block_depth -= 1
                i += 2
                if block_depth == 0:
                    state = "normal"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "dollar":
            assert dollar_tag is not None
            if sql.startswith(dollar_tag, i):
                out.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                state = "normal"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "single":
            out.append(ch)
            if ch == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                state = "normal"
            i += 1
            continue

        if state == "double":
            out.append(ch)
            if ch == '"':
                if i + 1 < len(sql) and sql[i + 1] == '"':
                    out.append('"')
                    i += 2
                    continue
                state = "normal"
            i += 1
            continue

        if sql.startswith("--", i):
            out.append("--")
            state = "line_comment"
            i += 2
            continue
        if sql.startswith("/*", i):
            out.append("/*")
            state = "block_comment"
            block_depth = 1
            i += 2
            continue
        if ch == "$":
            match = re.match(r"\$[A-Za-z_0-9]*\$", sql[i:])
            if match:
                dollar_tag = match.group(0)
                out.append(dollar_tag)
                state = "dollar"
                i += len(dollar_tag)
                continue
        if ch == "'":
            out.append(ch)
            state = "single"
        elif ch == '"':
            out.append(ch)
            state = "double"
        elif ch == "?" and i + 1 < len(sql) and sql[i + 1] in "|&":
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def postgres_sql(sql: str) -> str:
    return _qmark_to_format(sql)


class PostgresConnection:
    backend = "postgresql"

    TRANSIENT_STATES = {
        "08000", "08003", "08006", "08001",
        "40001",
        "40P01",
        "55P03",
        "57014",
        "57P01", "57P02", "57P03",
        "53300",
        "25P03",
    }

    CONNECTION_STATES = {"08000", "08003", "08006", "08001", "57P01", "57P02", "57P03", "25P03"}

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Graph Scale Dynamics requires Psycopg: pip install -e ."
            ) from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._dsn = dsn
        self._listening = False
        self._session_locks: dict[int, str] = {}
        self._held_locks: dict[int, str] = {}
        self.reconnects = 0
        self.raw = self._open()

    def _open(self):
        psycopg = self._psycopg
        try:
            raw = psycopg.connect(
                self._dsn,
                autocommit=True,
                row_factory=self._dict_row,
                connect_timeout=int(os.environ.get("GSD_DATABASE_CONNECT_TIMEOUT", "10")),
                application_name=os.environ.get(
                    "GSD_DATABASE_APPLICATION_NAME", "gsd"
                ),
            )
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        try:
            lock_ms = max(100, int(os.environ.get("GSD_DATABASE_LOCK_TIMEOUT_MS", "10000")))
            statement_ms = max(
                1000, int(os.environ.get("GSD_DATABASE_STATEMENT_TIMEOUT_MS", "300000"))
            )
            idle_ms = max(
                1000, int(os.environ.get("GSD_DATABASE_IDLE_TX_TIMEOUT_MS", "120000"))
            )
            raw.execute("SELECT set_config('lock_timeout', %s, false)",
                        (f"{lock_ms}ms",))
            raw.execute("SELECT set_config('statement_timeout', %s, false)",
                        (f"{statement_ms}ms",))
            raw.execute(
                "SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
                (f"{idle_ms}ms",),
            )
        except psycopg.Error as exc:
            raw.close()
            raise self._map_error(exc) from exc
        return raw

    @property
    def lost(self) -> bool:
        try:
            return bool(self.raw.closed) or bool(getattr(self.raw, "broken", False))
        except Exception:
            return True

    def keep_session_lock(self, key: int, name: str) -> None:
        self._session_locks[int(key)] = str(name)

    def forget_session_lock(self, key: int) -> None:
        self._session_locks.pop(int(key), None)

    def hold_lock(self, key: int, name: str) -> None:
        self._held_locks[int(key)] = str(name)

    def drop_lock(self, key: int) -> None:
        self._held_locks.pop(int(key), None)

    def _reconnect(self) -> bool:
        try:
            self.raw.close()
        except Exception:
            pass
        try:
            self.raw = self._open()
        except DatabaseOperationalError:
            return False
        for key, name in list(self._session_locks.items()):
            try:
                taken = bool(self.raw.execute("SELECT pg_try_advisory_lock(%s) AS taken", (key,)).fetchone()["taken"])
            except self._psycopg.Error:
                self.raw.close()
                return False
            if not taken:
                self._session_locks.clear()
                raise SessionLockLost(
                    f"the PostgreSQL session holding the lock {name!r} ended and another process holds that lock now; "
                    "this process held it to run alone, so it stops rather than run beside that one")
        self.reconnects += 1
        if self._listening:
            try:
                self.raw.execute(f"LISTEN {WORK_CHANNEL}")
            except self._psycopg.Error:
                self._listening = False
        return True

    def _session_lost(self, exc: BaseException) -> bool:
        return self.lost or getattr(exc, "sqlstate", None) in self.CONNECTION_STATES

    @property
    def closed(self) -> bool:
        try:
            return bool(self.raw.closed)
        except Exception:
            return True

    @property
    def in_transaction(self) -> bool:
        if self.closed:
            return False
        try:
            return int(self.raw.info.transaction_status) in (2, 3)
        except Exception:
            return False

    def rollback_if_open(self) -> bool:
        if not self.in_transaction:
            return False
        try:
            self.raw.execute("ROLLBACK")
            return True
        except Exception:
            return False

    def _map_error(self, exc: BaseException, *, transient: bool | None = None) -> DatabaseOperationalError:
        state = getattr(exc, "sqlstate", None)
        return DatabaseOperationalError(
            f"PostgreSQL operation failed{f' [{state}]' if state else ''}: {exc}",
            transient=(state in self.TRANSIENT_STATES) if transient is None else bool(transient),
            sqlstate=state,
        )

    def execute(self, sql: str, args: Iterable[Any] = ()):
        in_transaction = self.in_transaction
        try:
            return self.raw.execute(postgres_sql(sql), tuple(args))
        except self._psycopg.Error as exc:
            if not self._session_lost(exc):
                raise self._map_error(exc) from exc
            mapped = self._map_error(exc, transient=True)
            mapped.outcome_unknown = not safe_to_repeat(sql) and (
                not in_transaction or str(sql).strip().upper() == "COMMIT")
            held = dict(self._held_locks)
            reconnected = self._reconnect()
            if held:
                self._held_locks.clear()
                raise DatabaseOperationalError(
                    "the PostgreSQL session holding " + ", ".join(sorted(held.values()))
                    + f" ended ({exc}); the work under it stops rather than run on without the lock",
                    transient=False, sqlstate=getattr(exc, "sqlstate", None)) from exc
            if not reconnected or in_transaction or not safe_to_repeat(sql):
                raise mapped from exc
            try:
                return self.raw.execute(postgres_sql(sql), tuple(args))
            except self._psycopg.Error as again:
                raise self._map_error(again, transient=self._session_lost(again)) from again

    def stream(self, sql: str, args: Iterable[Any] = (), *, size: int = 1000):
        chunk = size if self._psycopg.pq.version() >= 170000 else 1
        try:
            yield from self.raw.cursor().stream(postgres_sql(sql), tuple(args), size=chunk)
        except self._psycopg.Error as exc:
            raise self._map_error(exc) from exc

    def executescript(self, sql: str):
        cursor = None
        for statement in split_sql_script(sql):
            cursor = self.execute(statement)
        return cursor

    def listen_for_work(self) -> None:
        if not self._listening:
            self.execute(f"LISTEN {WORK_CHANNEL}")
            self._listening = True

    def wait_for_work(self, timeout: float = 2.0, relevant=None) -> bool:
        self.listen_for_work()
        deadline = time.monotonic() + max(0.0, float(timeout))
        if self.lost and not self._reconnect():
            time.sleep(min(1.0, max(0.0, float(timeout))))
            return False
        try:
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                batch = list(self.raw.notifies(timeout=remaining, stop_after=1))
                if not batch:
                    return False
                if relevant is None or any(relevant(note.payload) for note in batch):
                    list(self.raw.notifies(timeout=0.0))
                    return True
        except self._psycopg.Error as exc:
            if self._session_lost(exc) and self._reconnect():
                return True
            raise self._map_error(exc, transient=self._session_lost(exc) or None) from exc

    def close(self) -> None:
        self.raw.close()


def split_sql_script(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    state = "normal"
    dollar_tag: str | None = None
    block_depth = 0
    i = 0
    while i < len(script):
        ch = script[i]

        if state == "line_comment":
            buf.append(ch)
            i += 1
            if ch == "\n":
                state = "normal"
            continue

        if state == "block_comment":
            if script.startswith("/*", i):
                buf.append("/*")
                block_depth += 1
                i += 2
            elif script.startswith("*/", i):
                buf.append("*/")
                block_depth -= 1
                i += 2
                if block_depth == 0:
                    state = "normal"
            else:
                buf.append(ch)
                i += 1
            continue

        if state == "dollar":
            assert dollar_tag is not None
            if script.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                state = "normal"
            else:
                buf.append(ch)
                i += 1
            continue

        if state == "single":
            buf.append(ch)
            if ch == "'":
                if i + 1 < len(script) and script[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                state = "normal"
            i += 1
            continue

        if state == "double":
            buf.append(ch)
            if ch == '"':
                if i + 1 < len(script) and script[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                state = "normal"
            i += 1
            continue

        if script.startswith("--", i):
            buf.append("--")
            state = "line_comment"
            i += 2
            continue
        if script.startswith("/*", i):
            buf.append("/*")
            block_depth = 1
            state = "block_comment"
            i += 2
            continue
        if ch == "$":
            match = re.match(r"\$[A-Za-z_0-9]*\$", script[i:])
            if match:
                dollar_tag = match.group(0)
                buf.append(dollar_tag)
                state = "dollar"
                i += len(dollar_tag)
                continue
        if ch == "'":
            buf.append(ch)
            state = "single"
            i += 1
            continue
        if ch == '"':
            buf.append(ch)
            state = "double"
            i += 1
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def connect_database(target: str | Path | None = None) -> PostgresConnection:
    return PostgresConnection(resolve_target(target))
