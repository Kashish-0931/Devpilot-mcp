from devpilot.checks.throttle import JournalThrottle
from devpilot.server import tools
from tests.checks.test_container_checks import FakeContainer, FakeDockerClient

WATCH_LIST = ["demo-app"]


def _broken_client() -> FakeDockerClient:
    container = FakeContainer(
        status="exited",
        attrs={"State": {"ExitCode": 1, "OOMKilled": False}, "RestartCount": 0, "Config": {}},
    )
    return FakeDockerClient({"demo-app": container})


def test_check_container_writes_watchdog_entry_on_problem(journal_store):
    throttle = JournalThrottle(window_seconds=600, clock=lambda: 0.0)

    tools.check_container(journal_store, _broken_client(), WATCH_LIST, throttle, "demo-app")

    entries = journal_store.recent()
    assert len(entries) == 1
    assert entries[0].source == "watchdog"
    assert "not_running" in entries[0].message


def test_check_container_throttles_repeated_problem(journal_store):
    now = [0.0]
    throttle = JournalThrottle(window_seconds=600, clock=lambda: now[0])
    client = _broken_client()

    tools.check_container(journal_store, client, WATCH_LIST, throttle, "demo-app")
    now[0] = 5.0
    tools.check_container(journal_store, client, WATCH_LIST, throttle, "demo-app")

    entries = journal_store.recent()
    assert len(entries) == 1  # second call within the window did not journal again


def test_check_container_no_journal_entry_when_healthy(journal_store):
    healthy = FakeDockerClient(
        {
            "demo-app": FakeContainer(
                status="running",
                attrs={"State": {"ExitCode": 0, "OOMKilled": False}, "RestartCount": 0, "Config": {}},
            )
        }
    )
    throttle = JournalThrottle(window_seconds=600, clock=lambda: 0.0)

    tools.check_container(journal_store, healthy, WATCH_LIST, throttle, "demo-app")

    assert journal_store.recent() == []
