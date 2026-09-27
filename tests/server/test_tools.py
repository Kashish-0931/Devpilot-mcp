import pytest
from mcp.server.mcpserver.exceptions import ToolError

from devpilot.server import tools


def test_get_recent_journal_entries_returns_dicts(journal_store):
    journal_store.record(source="human", level="info", message="hello")

    results = tools.get_recent_journal_entries(journal_store)

    assert isinstance(results, list)
    assert results[0]["message"] == "hello"


def test_log_journal_entry_writes_and_is_readable_back(journal_store):
    written = tools.log_journal_entry(journal_store, "made a decision", level="info")

    assert written["source"] == "human"
    assert written["message"] == "made a decision"

    results = tools.get_recent_journal_entries(journal_store)
    assert results[0]["id"] == written["id"]
    assert results[0]["source"] == "human"


def test_log_journal_entry_rejects_bad_level(journal_store):
    with pytest.raises(ToolError, match="level must be one of"):
        tools.log_journal_entry(journal_store, "hello", level="not-a-level")


def test_get_recent_journal_entries_rejects_limit_too_high(journal_store):
    with pytest.raises(ToolError, match="limit must be between"):
        tools.get_recent_journal_entries(journal_store, limit=101)


def test_get_recent_journal_entries_rejects_limit_too_low(journal_store):
    with pytest.raises(ToolError, match="limit must be between"):
        tools.get_recent_journal_entries(journal_store, limit=0)
