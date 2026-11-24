"""Tests for the ``create_admin`` CLI.

The psycopg connection is faked (no server), but the real email validation,
password policy, and Argon2 hashing run, and the emitted SQL/parameters are
asserted. Nothing secret may reach stdout/stderr.
"""
from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from backend.app.cli import create_admin as cli
from backend.app.core.security import verify_password

PASSWORD = "cli-admin-password"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.connection.calls.append((query, params))

    def fetchone(self):
        return self.connection.rows.pop(0) if self.connection.rows else None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeConnection:
    def __init__(self, rows: list | None = None) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self.rows = list(rows or [])
        self.committed = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False


@pytest.fixture
def fake_connect(monkeypatch):
    created: list[FakeConnection] = []
    state: dict = {"rows": [], "error": None, "dsn": None}

    def connect(dsn: str, **kwargs) -> FakeConnection:
        state["dsn"] = dsn
        if state["error"] is not None:
            raise state["error"]
        connection = FakeConnection(state["rows"])
        created.append(connection)
        return connection

    monkeypatch.setattr(cli.psycopg, "connect", connect)
    return created, state


def _env(monkeypatch, **overrides: str):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://app:secret-db-password@db.example.test/app"
    )
    monkeypatch.delenv("DB_SCHEMA", raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


def test_create_admin_inserts_an_approved_admin(monkeypatch, capsys, fake_connect):
    created, state = fake_connect
    state["rows"] = []
    _env(monkeypatch)

    code = cli.main(["--email", "  Admin@Example.TEST ", "--password", PASSWORD, "--admin"])

    assert code == 0
    (connection,) = created
    assert connection.committed is True
    (select_query, select_args), (insert_query, insert_args) = connection.calls
    assert "select id, app_role from" in select_query
    assert "lower(email) = %s" in select_query
    assert select_args == ("admin@example.test",)
    assert "insert into" in insert_query
    assert "is_approved, app_role" in insert_query
    assert insert_args[0] == "admin@example.test"
    assert verify_password(insert_args[1], PASSWORD)
    assert insert_args[2] == "admin"

    out = capsys.readouterr()
    assert "Created admin account admin@example.test" in out.out
    assert PASSWORD not in out.out + out.err
    assert insert_args[1] not in out.out + out.err
    assert "secret-db-password" not in out.out + out.err


def test_create_admin_updates_an_existing_account(monkeypatch, capsys, fake_connect):
    created, state = fake_connect
    user_id = uuid4()
    state["rows"] = [{"id": user_id, "app_role": "user"}]
    _env(monkeypatch, DB_SCHEMA="vidfetch")

    code = cli.main(["--email", "admin@example.test", "--password", PASSWORD])

    assert code == 0
    (connection,) = created
    (_, select_args), (update_query, update_args) = connection.calls
    assert select_args == ("admin@example.test",)
    assert 'update "vidfetch".profiles' in update_query
    assert "set password_hash = %s, is_approved = true" in update_query
    # Without --admin the existing role is preserved, not demoted.
    assert "app_role" not in update_query
    assert update_args[0] != PASSWORD
    assert verify_password(update_args[0], PASSWORD)
    assert update_args[1] == user_id
    assert "Updated user account admin@example.test" in capsys.readouterr().out


def test_create_admin_reports_the_preserved_role(monkeypatch, capsys, fake_connect):
    created, state = fake_connect
    user_id = uuid4()
    state["rows"] = [{"id": user_id, "app_role": "admin"}]
    _env(monkeypatch)

    code = cli.main(["--email", "admin@example.test", "--password", PASSWORD])

    assert code == 0
    (connection,) = created
    (select_query, _), (update_query, update_args) = connection.calls
    assert "select id, app_role" in select_query
    assert "app_role" not in update_query
    assert update_args[1] == user_id
    assert "Updated admin account admin@example.test" in capsys.readouterr().out


def test_create_admin_grants_admin_to_an_existing_account(
    monkeypatch, capsys, fake_connect
):
    created, state = fake_connect
    user_id = uuid4()
    state["rows"] = [{"id": user_id, "app_role": "user"}]
    _env(monkeypatch)

    code = cli.main(
        ["--email", "admin@example.test", "--password", PASSWORD, "--admin"]
    )

    assert code == 0
    (connection,) = created
    (_, _), (update_query, update_args) = connection.calls
    assert "app_role = %s" in update_query
    assert update_args[1] == "admin"
    assert update_args[2] == user_id
    assert verify_password(update_args[0], PASSWORD)
    assert "Updated admin account admin@example.test" in capsys.readouterr().out


def test_create_admin_requires_a_database_url(monkeypatch, capsys, fake_connect):
    created, _ = fake_connect
    monkeypatch.delenv("DATABASE_URL", raising=False)

    code = cli.main(["--email", "admin@example.test", "--password", PASSWORD])

    assert code == 2
    assert created == []
    assert "DATABASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize(
    "email,password",
    [
        ("not-an-email", PASSWORD),
        ("admin@example.test", "short"),
        ("admin@example.test", "x" * 201),
    ],
)
def test_create_admin_rejects_invalid_input(
    monkeypatch, capsys, fake_connect, email, password
):
    created, _ = fake_connect
    _env(monkeypatch)

    code = cli.main(["--email", email, "--password", password])

    assert code == 2
    assert created == []
    err = capsys.readouterr().err
    assert "Invalid input" in err
    assert password not in err


def test_create_admin_reports_database_errors_without_leaking_secrets(
    monkeypatch, capsys, fake_connect
):
    _, state = fake_connect
    state["error"] = psycopg.OperationalError(
        "connection failed for postgresql://app:secret-db-password@db/app"
    )
    _env(monkeypatch)

    code = cli.main(["--email", "admin@example.test", "--password", PASSWORD])

    assert code == 1
    captured = capsys.readouterr()
    assert "could not update the account" in captured.err
    assert "secret-db-password" not in captured.err
    assert PASSWORD not in captured.out + captured.err


def test_create_admin_rejects_an_invalid_schema(monkeypatch, capsys, fake_connect):
    created, _ = fake_connect
    _env(monkeypatch, DB_SCHEMA="not-a-schema")

    code = cli.main(["--email", "admin@example.test", "--password", PASSWORD])

    assert code == 2
    assert created == []
    assert "DB_SCHEMA" in capsys.readouterr().err
