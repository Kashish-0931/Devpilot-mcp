import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from mcp.server.mcpserver.exceptions import ToolError

from .redaction import redact

_EXTRA_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
_SNIPPET_BYTES = 200


def _ensure_allowed_host(watch_list: list[str], url: str) -> None:
    host = urlparse(url).hostname
    if host not in watch_list and host not in _EXTRA_ALLOWED_HOSTS:
        raise ToolError(f"host {host!r} is not a watched container or localhost")


def check_endpoint(watch_list: list[str], url: str, timeout: float = 10) -> dict:
    """Connection failures/timeouts to an ALLOWED host are a normal finding
    (returned in `error`), not a raised exception -- that's exactly the kind
    of thing this tool exists to report. An out-of-scope URL is rejected
    before any request is made."""
    _ensure_allowed_host(watch_list, url)

    start = time.monotonic()
    status_code = None
    body = b""
    error = None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status_code = response.status
            body = response.read(_SNIPPET_BYTES)
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        body = exc.read(_SNIPPET_BYTES) if hasattr(exc, "read") else b""
    except Exception as exc:  # noqa: BLE001 -- network failure is a finding, not our bug
        error = str(exc)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    snippet = redact(body.decode("utf-8", errors="replace"))

    return {
        "url": url,
        "status_code": status_code,
        "response_time_ms": elapsed_ms,
        "body_snippet": snippet,
        "error": error,
    }
