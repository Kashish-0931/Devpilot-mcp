import uuid
from decimal import Decimal

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


def test_to_item_converts_nested_floats_to_decimal():
    entry = JournalEntry(
        source="watchdog",
        level="warning",
        message="cpu high",
        metadata={"cpu_pct": 91.5, "thresholds": [10.0, 20.5], "nested": {"ratio": 0.75}},
    )

    item = entry.to_item()

    assert item["metadata"]["cpu_pct"] == Decimal("91.5")
    assert isinstance(item["metadata"]["cpu_pct"], Decimal)
    assert item["metadata"]["thresholds"] == [Decimal("10.0"), Decimal("20.5")]
    assert item["metadata"]["nested"]["ratio"] == Decimal("0.75")


def test_from_item_converts_decimals_back_to_numbers():
    item = {
        "id": "abc",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "source": "watchdog",
        "level": "warning",
        "message": "cpu high",
        "metadata": {
            "retries": Decimal("3"),
            "cpu_pct": Decimal("91.5"),
            "thresholds": [Decimal("10"), Decimal("20.5")],
        },
    }

    entry = JournalEntry.from_item(item)

    assert entry.metadata["retries"] == 3
    assert isinstance(entry.metadata["retries"], int)
    assert entry.metadata["cpu_pct"] == 91.5
    assert isinstance(entry.metadata["cpu_pct"], float)
    assert entry.metadata["thresholds"] == [10, 20.5]
    assert isinstance(entry.metadata["thresholds"][0], int)
