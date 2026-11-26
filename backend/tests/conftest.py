"""Shared pytest configuration for the backend test suite."""
from __future__ import annotations

from typing import Any


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires a real PostgreSQL database (TEST_DATABASE_URL)",
    )
