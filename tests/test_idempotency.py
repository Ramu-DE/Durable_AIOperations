"""Integration tests for tool_call_store (atomic idempotency)."""
import os
import sys
import uuid
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.db.dsql_client import get_connection
from src.db import tool_call_store


@pytest.fixture
def conn():
    c = get_connection()
    yield c
    c.close()


def _key():
    return f"TEST-{uuid.uuid4().hex[:12]}"


def test_begin_call_first_attempt(conn):
    key = _key()
    is_first = tool_call_store.begin_call(conn, key, "hold_seat", {"flight_id": "FL-100"})
    conn.commit()
    assert is_first is True


def test_begin_call_duplicate_returns_false(conn):
    key = _key()
    tool_call_store.begin_call(conn, key, "hold_seat", {})
    conn.commit()
    # Re-open (simulate second process)
    is_first = tool_call_store.begin_call(conn, key, "hold_seat", {})
    conn.commit()
    assert is_first is False


def test_complete_call_and_get_result(conn):
    key = _key()
    tool_call_store.begin_call(conn, key, "authorize_payment", {})
    result = {"booking_id": "BK-001", "status": "authorized"}
    tool_call_store.complete_call(conn, key, result)
    conn.commit()

    fetched = tool_call_store.get_result(conn, key)
    assert fetched == result


def test_get_result_returns_none_when_running(conn):
    key = _key()
    tool_call_store.begin_call(conn, key, "hold_seat", {})
    conn.commit()
    # Status is 'running' — get_result should return None (not yet succeeded)
    fetched = tool_call_store.get_result(conn, key)
    assert fetched is None


def test_duplicate_begin_then_complete_preserves_first(conn):
    key = _key()
    tool_call_store.begin_call(conn, key, "hold_seat", {})
    tool_call_store.complete_call(conn, key, {"v": 1})
    conn.commit()

    # Second attempt: begin returns False
    is_first = tool_call_store.begin_call(conn, key, "hold_seat", {})
    conn.commit()
    assert is_first is False

    # Result remains the first call's result
    assert tool_call_store.get_result(conn, key) == {"v": 1}
