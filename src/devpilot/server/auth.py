import hmac

from mcp.server.auth.provider import AccessToken, TokenVerifier


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, expected_token: str):
        self._expected = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._expected):
            return AccessToken(token=token, client_id="devpilot", scopes=[])
        return None
