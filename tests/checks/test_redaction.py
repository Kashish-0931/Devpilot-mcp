from devpilot.checks.redaction import redact


def test_redacts_password():
    assert redact("connecting with password=hunter2") == "connecting with password=[REDACTED]"


def test_redacts_token():
    assert redact("token=abc123xyz sent") == "token=[REDACTED] sent"


def test_redacts_secret():
    assert redact("secret=topsecret in config") == "secret=[REDACTED] in config"


def test_redacts_api_key():
    assert redact("api_key=sk-1234567890") == "api_key=[REDACTED]"


def test_redacts_bearer_token():
    assert redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc") == "Authorization: Bearer [REDACTED]"


def test_redacts_aws_access_key():
    assert redact("found AKIAABCDEFGHIJKLMNOP in logs") == "found [REDACTED_AWS_KEY] in logs"


def test_leaves_normal_text_alone():
    assert redact("container started successfully") == "container started successfully"


def test_is_case_insensitive():
    assert redact("PASSWORD=hunter2") == "PASSWORD=[REDACTED]"
