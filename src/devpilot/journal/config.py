import os

JOURNAL_TABLE_ENV_VAR = "DEVPILOT_JOURNAL_TABLE"
DEFAULT_JOURNAL_TABLE = "devpilot-journal"

WATCH_CONTAINERS_ENV_VAR = "DEVPILOT_WATCH_CONTAINERS"


def journal_table_name() -> str:
    return os.environ.get(JOURNAL_TABLE_ENV_VAR, DEFAULT_JOURNAL_TABLE)


def watch_containers() -> list[str]:
    raw = os.environ.get(WATCH_CONTAINERS_ENV_VAR, "")
    return [name.strip() for name in raw.split(",") if name.strip()]
