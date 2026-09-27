import asyncio

from devpilot.server.auth import StaticTokenVerifier


def test_correct_token_verifies():
    verifier = StaticTokenVerifier("secret-token")

    result = asyncio.run(verifier.verify_token("secret-token"))

    assert result is not None
    assert result.token == "secret-token"


def test_wrong_token_fails():
    verifier = StaticTokenVerifier("secret-token")

    result = asyncio.run(verifier.verify_token("wrong-token"))

    assert result is None


def test_missing_token_fails():
    verifier = StaticTokenVerifier("secret-token")

    result = asyncio.run(verifier.verify_token(""))

    assert result is None
