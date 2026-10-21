"""Strict URL syntax and scope checks, without network access."""

from urllib.parse import urlsplit, urlunsplit


def canonical_url(value: str) -> str:
    if (not value or len(value) > 2048 or not value.isascii()
            or any(character.isspace() or ord(character) < 32 for character in value)
            or any(character in value for character in ("\\", "%"))):
        raise ValueError("invalid URL syntax")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.port not in (None, 443) or parts.query):
        raise ValueError("HTTPS without credentials or query parameters is required")
    host = parts.hostname.lower()
    if host.endswith(".") or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789.-:" for character in host):
        raise ValueError("invalid host")
    path = parts.path or "/"
    if "//" in path or any(part in {".", ".."} for part in path.split("/")) or ";" in path:
        raise ValueError("ambiguous path")
    netloc = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", netloc, path, "", ""))


def in_scope(url: str, scopes: list[str]) -> bool:
    parsed = urlsplit(url)
    for scope in scopes:
        approved = urlsplit(scope)
        if parsed.netloc == approved.netloc and (
            parsed.path == approved.path or parsed.path.startswith(approved.path.rstrip("/") + "/")
        ):
            return True
    return False
