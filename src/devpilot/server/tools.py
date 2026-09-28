from dataclasses import asdict

from mcp.server.mcpserver.exceptions import ToolError

from devpilot.checks import container_checks, http_checks
from devpilot.checks.throttle import JournalThrottle
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


def check_container(
    store: JournalStore,
    docker_client,
    watch_list: list[str],
    throttle: JournalThrottle,
    name: str,
) -> dict:
    """Inspect a watched container's status; auto-logs a source="watchdog"
    journal entry the first time a problem is found (throttled, see
    JournalThrottle) -- never more than once per (container, problem type)
    per window."""
    result = container_checks.check_container(docker_client, watch_list, name)
    problem = container_checks.classify_problem(result)
    if problem and throttle.should_log(name, problem):
        store.record(
            source="watchdog",
            level="warning",
            message=f"{name}: {problem}",
            metadata=result,
        )
    return result


def tail_logs(
    docker_client,
    watch_list: list[str],
    name: str,
    lines: int = 50,
    errors_only: bool = False,
) -> list[str]:
    return container_checks.tail_logs(docker_client, watch_list, name, lines, errors_only)


def container_stats(docker_client, watch_list: list[str], name: str) -> dict:
    return container_checks.container_stats(docker_client, watch_list, name)


def check_endpoint(watch_list: list[str], url: str, timeout: float = 10) -> dict:
    return http_checks.check_endpoint(watch_list, url, timeout)
