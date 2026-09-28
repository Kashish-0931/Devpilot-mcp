import re

_KEY_VALUE_PATTERNS = [
    re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(token\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(secret\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(api_key\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE),
]
_AWS_KEY_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}")


def redact(text: str) -> str:
    """Best-effort secret redaction for log lines / response bodies before they
    leave DevPilot. Not a guarantee against every possible secret shape."""
    for pattern in _KEY_VALUE_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _AWS_KEY_PATTERN.sub("[REDACTED_AWS_KEY]", text)
    return text
