"""Metadata sanitization, independent of document bytes and their hashes."""

import os
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


def safe_text(value: str, *, prose_labels: bool = False) -> str:
    """Mask secrets. With prose_labels, "Password: Best Practices" stays readable; "password=x" never does."""
    value = unicodedata.normalize("NFC", value).strip()
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    def strip_url_secrets(match):
        try:
            parts = urlsplit(match.group())
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
        except ValueError:
            return "[REDACTED URL]"
    value = re.sub(r"https?://[^\s]+", strip_url_secrets, value)
    for key, secret in os.environ.items():
        if secret and re.search(r"(?:^|_)(?:API_KEY|TOKEN|PASSWORD|SECRET)(?:$|_)", key, re.I):
            value = value.replace(secret, "[REDACTED]")
    separator = r"\s*=\s*|:(?=\S)" if prose_labels else r"\s*[=:]\s*"
    value = re.sub(
        rf"(?i)(api[_-]?key|access[_-]?token|password|secret|authorization)({separator})[^\s&]+",
        r"\1\2[REDACTED]", value,
    )
    return value


def safe_title(value: str) -> str:
    """For descriptive metadata, where a label followed by words is ordinary prose."""
    return safe_text(value, prose_labels=True)


def safe_source_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("source URL must be HTTP or HTTPS")
    # Credentials, query strings and fragments may carry keys or signed tokens.
    return safe_text(urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")))
