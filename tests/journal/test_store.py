def test_record_then_recent_returns_it(journal_store):
    entry = journal_store.record(source="human", level="info", message="hello")

    results = journal_store.recent()

    assert len(results) == 1
    assert results[0] == entry


def test_recent_is_newest_first(journal_store):
    first = journal_store.record(source="human", level="info", message="first")
    second = journal_store.record(source="human", level="info", message="second")

    results = journal_store.recent()

    assert [e.id for e in results] == [second.id, first.id]


def test_recent_respects_limit(journal_store):
    for i in range(5):
        journal_store.record(source="human", level="info", message=f"entry {i}")

    results = journal_store.recent(limit=2)

    assert len(results) == 2


def test_metadata_round_trips(journal_store):
    entry = journal_store.record(
        source="watchdog",
        level="error",
        message="container crashed",
        metadata={"container_id": "abc123", "exit_code": 137},
    )

    (result,) = journal_store.recent()

    assert result.metadata == entry.metadata
