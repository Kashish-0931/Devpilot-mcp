from dataclasses import asdict

from mcp.server.mcpserver.exceptions import ToolError

from devpilot.journal.models import VALID_LEVELS
from devpilot.journal.store import JournalStore

MIN_LIMIT = 1
MAX_LIMIT = 100


def get_recent_journal_entries(store: JournalStore, limit: int = 50) -> list[dict]:
    if not (MIN_LIMIT <= limit <= MAX_LIMIT):
        raise ToolError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}, got {limit}")

    return [asdict(entry) for entry in store.recent(limit)]


def log_journal_entry(
    store: JournalStore,
    message: str,
    level: str = "info",
    metadata: dict | None = None,
) -> dict:
    """Always source="human" -- this tool is for people, not internal code."""
    if level not in VALID_LEVELS:
        raise ToolError(f"level must be one of {sorted(VALID_LEVELS)}, got {level!r}")

    entry = store.record(source="human", level=level, message=message, metadata=metadata or {})
    return asdict(entry)
