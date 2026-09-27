from dataclasses import asdict

from devpilot.journal.store import JournalStore


def get_recent_journal_entries(store: JournalStore, limit: int = 50) -> list[dict]:
    return [asdict(entry) for entry in store.recent(limit)]


def log_journal_entry(
    store: JournalStore,
    message: str,
    level: str = "info",
    metadata: dict | None = None,
) -> dict:
    """Always source="human" -- this tool is for people, not internal code."""
    entry = store.record(source="human", level=level, message=message, metadata=metadata or {})
    return asdict(entry)
