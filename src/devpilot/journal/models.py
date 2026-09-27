from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

VALID_LEVELS = {"info", "warning", "error", "critical"}


def _floats_to_decimal(value: Any) -> Any:
    """DynamoDB has no float type -- recursively convert floats to Decimal."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats_to_decimal(v) for v in value]
    return value


def _decimals_to_numbers(value: Any) -> Any:
    """Reverse of _floats_to_decimal -- DynamoDB always returns Decimal for numbers."""
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if as_int == value else float(value)
    if isinstance(value, dict):
        return {k: _decimals_to_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals_to_numbers(v) for v in value]
    return value


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
            "metadata": _floats_to_decimal(self.metadata),
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "JournalEntry":
        return cls(
            source=item["source"],
            level=item["level"],
            message=item["message"],
            metadata=_decimals_to_numbers(item.get("metadata", {})),
            id=item["id"],
            timestamp=item.get("timestamp") or item["sk"].split("#", 1)[0],
        )
