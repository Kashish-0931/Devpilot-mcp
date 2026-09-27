import uuid

import pytest

from devpilot.journal.models import JournalEntry


def test_defaults_are_generated():
    entry = JournalEntry(source="human", level="info", message="hello")

    assert uuid.UUID(entry.id)
    assert entry.timestamp
    assert entry.metadata == {}


def test_bad_level_raises():
    with pytest.raises(ValueError):
        JournalEntry(source="human", level="not-a-level", message="hello")


def test_entry_is_frozen():
    entry = JournalEntry(source="human", level="info", message="hello")

    with pytest.raises(Exception):
        entry.message = "changed"  # type: ignore[misc]


def test_to_item_from_item_round_trip():
    entry = JournalEntry(
        source="watchdog",
        level="warning",
        message="disk usage high",
        metadata={"disk_pct": 91},
    )

    item = entry.to_item()
    assert item["pk"] == "journal"
    assert item["sk"] == f"{entry.timestamp}#{entry.id}"

    restored = JournalEntry.from_item(item)
    assert restored == entry
