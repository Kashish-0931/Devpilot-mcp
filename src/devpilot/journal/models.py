from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_LEVELS = {"info", "warning", "error", "critical"}


@dataclass(frozen=True)
class JournalEntry:
    """A single event recorded in DevPilot's journal (the audit/diagnosis trail)."""

    source: str
    level: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if self.level not in VALID_LEVELS:
            raise ValueError(f"level must be one of {VALID_LEVELS}, got {self.level!r}")

    def to_item(self) -> dict[str, Any]:
        """Serialize to a DynamoDB item, keyed for a single partition ordered by time."""
        return {
            "pk": "journal",
            "sk": f"{self.timestamp}#{self.id}",
            "id": self.id,
            "timestamp": self.timestamp,
            "source": self.source,
            "level": self.level,
            "message": self.message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "JournalEntry":
        return cls(
            source=item["source"],
            level=item["level"],
            message=item["message"],
            metadata=item.get("metadata", {}),
            id=item["id"],
            timestamp=item.get("timestamp") or item["sk"].split("#", 1)[0],
        )
