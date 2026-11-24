from __future__ import annotations

import importlib.util
import os
import uuid
from dataclasses import dataclass

import pytest

from graph_scale_dynamics.db.connection import connect_database, postgres_schema_dsn

REQUIRE_NATIVE_ENV = "GSD_REQUIRE_NATIVE_POSTGRES_TESTS"


@dataclass(frozen=True)
class IsolatedPostgresSchema:
    base: str
    schema: str
    dsn: str
    reference: str


def _unavailable(exc: BaseException) -> None:
    message = (
        "folder-local PostgreSQL is unavailable in this test environment: "
        f"{type(exc).__name__}: {exc}"
    )
    if os.environ.get(REQUIRE_NATIVE_ENV) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


@pytest.fixture(scope="session")
def folder_postgres_base() -> str:
    if importlib.util.find_spec("psycopg") is None:
        _unavailable(RuntimeError("Psycopg is not installed in this interpreter"))
    try:
        conn = connect_database("folder")
    except BaseException as exc:
        _unavailable(exc)
        raise AssertionError("unreachable") from exc
    try:
        row = conn.execute(
            "SELECT inet_server_addr() AS tcp_addr, current_database() AS db"
        ).fetchone()
        if row.get("tcp_addr") is not None:
            pytest.fail(
                f"folder-local PostgreSQL unexpectedly accepted TCP: {row['tcp_addr']}",
                pytrace=False,
            )
    finally:
        conn.close()
    return "folder"


def _create_schema(base: str) -> IsolatedPostgresSchema:
    schema = "gsd_test_" + uuid.uuid4().hex[:16]
    admin = connect_database(base)
    try:
        admin.execute(f"CREATE SCHEMA {schema}")
    finally:
        admin.close()
    return IsolatedPostgresSchema(
        base=base,
        schema=schema,
        dsn=postgres_schema_dsn(base, schema),
        reference=f"folder-schema:{schema}",
    )


def _drop_schema(value: IsolatedPostgresSchema) -> None:
    admin = connect_database(value.base)
    try:
        admin.execute(f"DROP SCHEMA IF EXISTS {value.schema} CASCADE")
    finally:
        admin.close()


@pytest.fixture
def postgres_schema_factory(folder_postgres_base: str):
    created: list[IsolatedPostgresSchema] = []

    def create() -> IsolatedPostgresSchema:
        value = _create_schema(folder_postgres_base)
        created.append(value)
        return value

    try:
        yield create
    finally:
        for value in reversed(created):
            _drop_schema(value)


@pytest.fixture
def isolated_postgres_schema(postgres_schema_factory):
    yield postgres_schema_factory()
