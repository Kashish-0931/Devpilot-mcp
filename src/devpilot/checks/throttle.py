import time as _time
from typing import Callable


class JournalThrottle:
    """Limits how often a (container, problem_type) pair may write a watchdog
    journal entry. In-memory only -- resets on restart, not shared across
    multiple DevPilot instances. Fine for a single-instance personal project."""

    def __init__(self, window_seconds: float = 600, clock: Callable[[], float] = _time.monotonic):
        self._window = window_seconds
        self._clock = clock
        self._last_logged: dict[tuple[str, str], float] = {}

    def should_log(self, name: str, problem_type: str) -> bool:
        key = (name, problem_type)
        now = self._clock()
        last = self._last_logged.get(key)
        if last is not None and (now - last) < self._window:
            return False
        self._last_logged[key] = now
        return True
