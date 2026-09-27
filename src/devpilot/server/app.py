from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from devpilot.journal.store import JournalStore
from devpilot.server import tools
from devpilot.server.auth import StaticTokenVerifier


def create_app(token: str, store: JournalStore | None = None, port: int = 8080):
    store = store or JournalStore()

    mcp = MCPServer(
        "devpilot",
        token_verifier=StaticTokenVerifier(token),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(f"http://localhost:{port}"),
            resource_server_url=AnyHttpUrl(f"http://localhost:{port}/mcp"),
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

    return mcp.streamable_http_app()
