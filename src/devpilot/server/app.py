import docker
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl

from devpilot.checks.docker_client import get_docker_client
from devpilot.checks.throttle import JournalThrottle
from devpilot.journal.config import watch_containers
from devpilot.journal.store import JournalStore
from devpilot.server import tools
from devpilot.server.auth import StaticTokenVerifier


def create_app(
    token: str,
    store: JournalStore | None = None,
    port: int = 8080,
    docker_client=None,
    watch_list: list[str] | None = None,
    throttle: JournalThrottle | None = None,
):
    store = store or JournalStore()
    watch_list = watch_containers() if watch_list is None else watch_list
    throttle = throttle or JournalThrottle()

    def _resolve_docker_client():
        if docker_client is not None:
            return docker_client
        try:
            return get_docker_client()
        except docker.errors.DockerException as exc:
            raise ToolError(f"could not reach Docker: {exc}")

    mcp = MCPServer(
        "devpilot",
        token_verifier=StaticTokenVerifier(token),
        auth=AuthSettings(
            # 127.0.0.1, not localhost -- localhost can resolve to the IPv6
            # loopback on Windows, which then fails the SDK's protected-resource
            # metadata match against whatever host a client actually connects to.
            issuer_url=AnyHttpUrl(f"http://127.0.0.1:{port}"),
            resource_server_url=AnyHttpUrl(f"http://127.0.0.1:{port}/mcp"),
            required_scopes=[],
            validate_token_resource=False,
        ),
    )

    @mcp.tool()
    def get_recent_journal_entries(limit: int = 50) -> list[dict]:
        """Return the most recent DevPilot journal entries, newest first."""
        return tools.get_recent_journal_entries(store, limit)

    @mcp.tool()
    def log_journal_entry(
        message: str, level: str = "info", metadata: dict | None = None
    ) -> dict:
        """Record a human-authored note or decision in the DevPilot journal."""
        return tools.log_journal_entry(store, message, level, metadata)

    @mcp.tool()
    def check_container(name: str) -> dict:
        """Check a watched container's status (running/exited/health/restarts)."""
        return tools.check_container(store, _resolve_docker_client(), watch_list, throttle, name)

    @mcp.tool()
    def tail_logs(name: str, lines: int = 50, errors_only: bool = False) -> list[str]:
        """Read a watched container's recent logs, optionally filtered to error lines."""
        return tools.tail_logs(_resolve_docker_client(), watch_list, name, lines, errors_only)

    @mcp.tool()
    def container_stats(name: str) -> dict:
        """One-shot CPU/memory usage for a watched container."""
        return tools.container_stats(_resolve_docker_client(), watch_list, name)

    @mcp.tool()
    def check_endpoint(url: str, timeout: float = 10) -> dict:
        """HTTP-check a watched container's endpoint (or localhost); reports
        status code, latency, and a redacted body snippet."""
        return tools.check_endpoint(watch_list, url, timeout)

    return mcp.streamable_http_app()
