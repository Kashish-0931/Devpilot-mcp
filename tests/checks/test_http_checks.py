import urllib.error

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from devpilot.checks import http_checks

WATCH_LIST = ["demo-app"]


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, n=-1):
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_check_endpoint_200(monkeypatch):
    monkeypatch.setattr(
        http_checks.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse(200, b'{"status": "ok"}'),
    )

    result = http_checks.check_endpoint(WATCH_LIST, "http://demo-app:5000/health")

    assert result["status_code"] == 200
    assert result["error"] is None
    assert "ok" in result["body_snippet"]


def test_check_endpoint_500(monkeypatch):
    def raise_http_error(url, timeout):
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(http_checks.urllib.request, "urlopen", raise_http_error)

    result = http_checks.check_endpoint(WATCH_LIST, "http://demo-app:5000/api")

    assert result["status_code"] == 500


def test_check_endpoint_timeout(monkeypatch):
    def raise_timeout(url, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(http_checks.urllib.request, "urlopen", raise_timeout)

    result = http_checks.check_endpoint(WATCH_LIST, "http://demo-app:5000/api")

    assert result["status_code"] is None
    assert "timed out" in result["error"]


def test_check_endpoint_rejects_unwatched_host():
    with pytest.raises(ToolError, match="not a watched container"):
        http_checks.check_endpoint(WATCH_LIST, "http://evil.example.com/steal-data")


def test_check_endpoint_allows_localhost(monkeypatch):
    monkeypatch.setattr(
        http_checks.urllib.request, "urlopen", lambda url, timeout: _FakeResponse(200, b"ok")
    )

    result = http_checks.check_endpoint(WATCH_LIST, "http://localhost:8080/health")

    assert result["status_code"] == 200


def test_check_endpoint_redacts_body(monkeypatch):
    monkeypatch.setattr(
        http_checks.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeResponse(200, b"token=abc123secretvalue"),
    )

    result = http_checks.check_endpoint(WATCH_LIST, "http://demo-app:5000/health")

    assert "abc123secretvalue" not in result["body_snippet"]
    assert "[REDACTED]" in result["body_snippet"]
