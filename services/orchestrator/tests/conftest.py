"""Shared pytest fixtures for orchestrator tests."""
import os
import sqlite3
import pytest

# Force UTC for deterministic time tests.
os.environ.setdefault("TZ", "UTC")


@pytest.fixture
def memory_db():
    """In-memory sqlite connection with row factory, for store tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    yield conn
    conn.close()
