import os

JOURNAL_TABLE_ENV_VAR = "DEVPILOT_JOURNAL_TABLE"
DEFAULT_JOURNAL_TABLE = "devpilot-journal"


def journal_table_name() -> str:
    return os.environ.get(JOURNAL_TABLE_ENV_VAR, DEFAULT_JOURNAL_TABLE)
