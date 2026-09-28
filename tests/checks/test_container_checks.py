import docker
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from devpilot.checks import container_checks

WATCH_LIST = ["demo-app"]


class FakeContainer:
    def __init__(self, status="running", attrs=None, logs=b"", stats=None):
        self.status = status
        self.attrs = attrs or {}
        self._logs = logs
        self._stats = stats or {}

    def logs(self, **kwargs):
        return self._logs

    def stats(self, **kwargs):
        return self._stats


class FakeContainers:
    def __init__(self, containers: dict[str, FakeContainer], unreachable: bool = False):
        self._containers = containers
        self._unreachable = unreachable

    def get(self, name):
        if self._unreachable:
            raise docker.errors.DockerException("Docker daemon unreachable")
        if name not in self._containers:
            raise docker.errors.NotFound(f"no such container: {name}")
        return self._containers[name]


class FakeDockerClient:
    def __init__(self, containers: dict[str, FakeContainer] | None = None, unreachable: bool = False):
        self.containers = FakeContainers(containers or {}, unreachable=unreachable)


def make_client(container: FakeContainer, name: str = "demo-app") -> FakeDockerClient:
    return FakeDockerClient({name: container})


def test_check_container_running():
    container = FakeContainer(
        status="running",
        attrs={
            "State": {"ExitCode": 0, "OOMKilled": False, "StartedAt": "t1", "FinishedAt": ""},
            "RestartCount": 0,
            "Config": {"Image": "demo-app:latest"},
        },
    )
    result = container_checks.check_container(make_client(container), WATCH_LIST, "demo-app")

    assert result["status"] == "running"
    assert result["exit_code"] == 0
    assert result["oom_killed"] is False
    assert result["health"] is None
    assert container_checks.classify_problem(result) is None


def test_check_container_exited():
    container = FakeContainer(
        status="exited",
        attrs={"State": {"ExitCode": 1, "OOMKilled": False}, "RestartCount": 2, "Config": {}},
    )
    result = container_checks.check_container(make_client(container), WATCH_LIST, "demo-app")

    assert result["status"] == "exited"
    assert container_checks.classify_problem(result) == "not_running"


def test_check_container_oom_killed():
    container = FakeContainer(
        status="exited",
        attrs={"State": {"ExitCode": 137, "OOMKilled": True}, "RestartCount": 0, "Config": {}},
    )
    result = container_checks.check_container(make_client(container), WATCH_LIST, "demo-app")

    assert result["oom_killed"] is True
    assert container_checks.classify_problem(result) == "oom_killed"


def test_check_container_restarting():
    container = FakeContainer(
        status="restarting",
        attrs={"State": {"ExitCode": 1, "OOMKilled": False}, "RestartCount": 5, "Config": {}},
    )
    result = container_checks.check_container(make_client(container), WATCH_LIST, "demo-app")

    assert result["status"] == "restarting"
    assert result["restart_count"] == 5
    assert container_checks.classify_problem(result) == "not_running"


def test_check_container_unhealthy():
    container = FakeContainer(
        status="running",
        attrs={
            "State": {"ExitCode": 0, "OOMKilled": False, "Health": {"Status": "unhealthy"}},
            "RestartCount": 0,
            "Config": {},
        },
    )
    result = container_checks.check_container(make_client(container), WATCH_LIST, "demo-app")

    assert result["health"] == "unhealthy"
    assert container_checks.classify_problem(result) == "unhealthy"


def test_check_container_not_found():
    client = FakeDockerClient({})
    with pytest.raises(ToolError, match="not found"):
        container_checks.check_container(client, WATCH_LIST, "demo-app")


def test_check_container_not_in_watch_list():
    client = FakeDockerClient({})
    with pytest.raises(ToolError, match="DEVPILOT_WATCH_CONTAINERS"):
        container_checks.check_container(client, WATCH_LIST, "some-other-container")


def test_check_container_docker_unreachable():
    client = FakeDockerClient(unreachable=True)
    with pytest.raises(ToolError, match="could not reach Docker"):
        container_checks.check_container(client, WATCH_LIST, "demo-app")


def test_tail_logs_returns_lines():
    container = FakeContainer(logs=b"2026-01-01T00:00:00 starting up\n2026-01-01T00:00:01 ready\n")
    lines = container_checks.tail_logs(make_client(container), WATCH_LIST, "demo-app")

    assert len(lines) == 2
    assert "starting up" in lines[0]


def test_tail_logs_errors_only_filters():
    container = FakeContainer(
        logs=b"INFO: all good\nERROR: could not connect to database\nINFO: retrying\n"
    )
    lines = container_checks.tail_logs(
        make_client(container), WATCH_LIST, "demo-app", errors_only=True
    )

    assert len(lines) == 1
    assert "ERROR" in lines[0]


def test_tail_logs_clamps_line_count():
    container = FakeContainer(logs=b"")
    # Just confirm this doesn't raise for out-of-range values.
    container_checks.tail_logs(make_client(container), WATCH_LIST, "demo-app", lines=10_000)
    container_checks.tail_logs(make_client(container), WATCH_LIST, "demo-app", lines=0)


def test_container_stats():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200_000_000, "percpu_usage": [1, 1]},
            "system_cpu_usage": 1_000_000_000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100_000_000},
            "system_cpu_usage": 900_000_000,
        },
        "memory_stats": {"usage": 50_000_000, "limit": 100_000_000},
    }
    container = FakeContainer(stats=stats)
    result = container_checks.container_stats(make_client(container), WATCH_LIST, "demo-app")

    assert result["memory_usage_bytes"] == 50_000_000
    assert result["memory_limit_bytes"] == 100_000_000
    assert result["memory_percent"] == 50.0
    # cpu_delta=100_000_000, system_delta=100_000_000, online_cpus=2 -> 200%
    assert result["cpu_percent"] == pytest.approx(200.0)
