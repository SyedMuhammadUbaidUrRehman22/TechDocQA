"""Finite HTTPS fetches with public DNS validation and pinned TLS destinations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import certifi
import urllib3

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.urls import canonical_url, in_scope
from techdocqa.settings import OnlineSettings, OnlineSource


def url_error():
    return TechDocQAError("URL_NOT_ALLOWED", "URL is outside the approved HTTPS policy.", stage="fetch")


def validate_url(value: str, source: OnlineSource) -> str:
    try:
        url = canonical_url(value)
    except ValueError:
        raise url_error() from None
    if not in_scope(url, source.scopes):
        raise url_error()
    return url


def public_addresses(host: str) -> list[str]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise TechDocQAError("DNS_FAILED", "Documentation host resolution failed.", stage="fetch", retryable=True) from None
    addresses = sorted({answer[4][0] for answer in answers})
    if not addresses:
        raise TechDocQAError("DNS_FAILED", "Documentation host has no usable addresses.", stage="fetch", retryable=True)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise url_error() from None
        if (not ip.is_global or ip.is_reserved or ip.is_multicast
                or getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
                or getattr(ip, "teredo", None)):
            raise url_error()
    return addresses


@dataclass(frozen=True)
class FetchedPage:
    body: bytes
    final_url: str
    content_type: str
    retrieved_at: str
    etag: str | None
    last_modified: str | None
    content_type_header: str


class SafeFetcher:
    def __init__(self, policy: OnlineSettings, max_bytes: int):
        self.policy = policy
        self.max_bytes = max_bytes
        self.last_request = {}

    def fetch(self, requested_url: str, source: OnlineSource) -> FetchedPage:
        url = validate_url(requested_url, source)
        redirects = 0
        retries = 0
        while True:
            host = urlsplit(url).hostname
            addresses = public_addresses(host)
            remaining = self.policy.request_interval_seconds - (time.monotonic() - self.last_request.get(host, 0))
            if remaining > 0:
                time.sleep(remaining)
            self.last_request[host] = time.monotonic()
            try:
                # Connect to this validated IP, never resolve the hostname again.
                with urllib3.HTTPSConnectionPool(
                    addresses[retries % len(addresses)], port=443, maxsize=1, block=True,
                    server_hostname=host, assert_hostname=host,
                    cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
                ) as pool:
                    response = pool.urlopen(
                        "GET", urlsplit(url).path, headers={
                            "Host": host, "Accept": "text/html, application/xhtml+xml",
                            "Accept-Encoding": "identity", "User-Agent": "TechDocQA/0.1 documentation-ingestion",
                        }, redirect=False, retries=False, preload_content=False, decode_content=False,
                        assert_same_host=False,
                        timeout=urllib3.Timeout(connect=self.policy.connect_timeout_seconds,
                                                read=self.policy.read_timeout_seconds),
                    )
                    try:
                        if response.status in {301, 302, 303, 307, 308}:
                            if redirects >= self.policy.max_redirects:
                                raise TechDocQAError("REDIRECT_LIMIT", "Documentation redirect limit exceeded.", stage="fetch")
                            location = response.headers.get("Location")
                            if not location:
                                raise TechDocQAError("INVALID_RESPONSE", "Redirect destination is missing.", stage="fetch")
                            url = validate_url(urljoin(url, location), source)
                            redirects += 1
                            continue
                        if response.status == 429 or 500 <= response.status <= 599:
                            code = "HTTP_RATE_LIMITED" if response.status == 429 else "HTTP_SERVER_ERROR"
                            if retries >= self.policy.retries:
                                raise TechDocQAError(code, "Documentation service remained unavailable after bounded retries.", stage="fetch", retryable=True)
                            delay = self.retry_delay(response.headers.get("Retry-After"), retries)
                            if delay > 10:
                                raise TechDocQAError(code, "Server requested a later retry.", stage="fetch", retryable=True)
                            retries += 1
                            time.sleep(delay)
                            continue
                        if response.status != 200:
                            code = "HTTP_NOT_FOUND" if response.status == 404 else "HTTP_ERROR"
                            raise TechDocQAError(code, "Documentation page could not be retrieved.", stage="fetch")
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if content_type not in {"text/html", "application/xhtml+xml"}:
                            raise TechDocQAError("UNSUPPORTED_CONTENT_TYPE", "Only HTML documentation responses are supported.", stage="fetch")
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            raise TechDocQAError("UNSUPPORTED_CONTENT_ENCODING", "Compressed responses are not accepted.", stage="fetch")
                        length = response.headers.get("Content-Length")
                        if length is not None:
                            if not length.isdecimal():
                                raise TechDocQAError("INVALID_RESPONSE", "Response length is invalid.", stage="fetch")
                            if int(length) > self.max_bytes:
                                raise TechDocQAError("FILE_TOO_LARGE", "Response exceeds the configured byte limit.", stage="fetch")
                        body = response.read(self.max_bytes + 1, decode_content=False)
                        if len(body) > self.max_bytes:
                            raise TechDocQAError("FILE_TOO_LARGE", "Response exceeds the configured byte limit.", stage="fetch")
                        return FetchedPage(body, url, content_type, datetime.now(timezone.utc).isoformat(),
                                           self.safe_header(response.headers.get("ETag")),
                                           self.safe_header(response.headers.get("Last-Modified")),
                                           self.safe_header(response.headers.get("Content-Type")))
                    finally:
                        response.close()
            except (urllib3.exceptions.HTTPError, OSError) as error:
                if isinstance(error, urllib3.exceptions.SSLError):
                    raise TechDocQAError("TLS_FAILED", "Documentation TLS verification failed.", stage="fetch") from None
                if retries >= self.policy.retries:
                    code = "FETCH_TIMEOUT" if isinstance(error, (urllib3.exceptions.TimeoutError, TimeoutError)) else "FETCH_FAILED"
                    raise TechDocQAError(code, "Documentation request failed after bounded retries.", stage="fetch", retryable=True) from None
                time.sleep(2 ** retries)
                retries += 1

    @staticmethod
    def retry_delay(value: str | None, retries: int) -> float:
        if value:
            if value.isdecimal():
                return float(value)
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
        return 2 ** retries

    @staticmethod
    def safe_header(value: str | None) -> str | None:
        from techdocqa.privacy import safe_text
        return safe_text(value[:500]) if value else None
