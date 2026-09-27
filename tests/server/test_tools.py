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
