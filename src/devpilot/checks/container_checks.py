import docker
from mcp.server.mcpserver.exceptions import ToolError

from .redaction import redact

MIN_LOG_LINES = 1
MAX_LOG_LINES = 500

_ERROR_KEYWORDS = ("ERROR", "EXCEPTION", "TRACEBACK", "CRITICAL", "FATAL")


def ensure_watched(watch_list: list[str], name: str) -> None:
    if name not in watch_list:
        raise ToolError(f"{name!r} is not in DEVPILOT_WATCH_CONTAINERS")


def _get_container(docker_client, name: str):
    try:
        return docker_client.containers.get(name)
    except docker.errors.NotFound:
        raise ToolError(f"container {name!r} not found")
    except docker.errors.DockerException as exc:
        raise ToolError(f"could not reach Docker: {exc}")


def check_container(docker_client, watch_list: list[str], name: str) -> dict:
    ensure_watched(watch_list, name)
    container = _get_container(docker_client, name)
    attrs = container.attrs
    state = attrs.get("State", {})
    health = state.get("Health", {}).get("Status")
    return {
        "name": name,
        "status": container.status,
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "restart_count": attrs.get("RestartCount"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "image": attrs.get("Config", {}).get("Image"),
        "health": health,
    }


def classify_problem(check_result: dict) -> str | None:
    if check_result.get("oom_killed"):
        return "oom_killed"
    if check_result.get("status") != "running":
        return "not_running"
    if check_result.get("health") == "unhealthy":
        return "unhealthy"
    return None


def tail_logs(
    docker_client, watch_list: list[str], name: str, lines: int = 50, errors_only: bool = False
) -> list[str]:
    ensure_watched(watch_list, name)
    lines = max(MIN_LOG_LINES, min(lines, MAX_LOG_LINES))
    container = _get_container(docker_client, name)
    try:
        raw = container.logs(tail=lines, timestamps=True, stdout=True, stderr=True)
    except docker.errors.DockerException as exc:
        raise ToolError(f"could not reach Docker: {exc}")

    text = raw.decode("utf-8", errors="replace")
    out_lines = [redact(line) for line in text.splitlines()]

    if errors_only:
        out_lines = [
            line for line in out_lines if any(keyword in line.upper() for keyword in _ERROR_KEYWORDS)
        ]
    return out_lines


def _cpu_percent(stats: dict) -> float | None:
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    cpu_usage = cpu_stats.get("cpu_usage", {})
    precpu_usage = precpu_stats.get("cpu_usage", {})

    cpu_total = cpu_usage.get("total_usage")
    precpu_total = precpu_usage.get("total_usage")
    system_cpu = cpu_stats.get("system_cpu_usage")
    presystem_cpu = precpu_stats.get("system_cpu_usage")

    if None in (cpu_total, precpu_total, system_cpu, presystem_cpu):
        return None

    cpu_delta = cpu_total - precpu_total
    system_delta = system_cpu - presystem_cpu
    if system_delta <= 0:
        return None

    online_cpus = cpu_stats.get("online_cpus") or len(cpu_usage.get("percpu_usage") or [1])
    return (cpu_delta / system_delta) * online_cpus * 100.0


def container_stats(docker_client, watch_list: list[str], name: str) -> dict:
    ensure_watched(watch_list, name)
    container = _get_container(docker_client, name)
    try:
        stats = container.stats(stream=False)
    except docker.errors.DockerException as exc:
        raise ToolError(f"could not reach Docker: {exc}")

    memory_stats = stats.get("memory_stats", {})
    usage = memory_stats.get("usage")
    limit = memory_stats.get("limit")
    memory_percent = (usage / limit * 100.0) if usage and limit else None

    return {
        "name": name,
        "cpu_percent": _cpu_percent(stats),
        "memory_usage_bytes": usage,
        "memory_limit_bytes": limit,
        "memory_percent": memory_percent,
    }
