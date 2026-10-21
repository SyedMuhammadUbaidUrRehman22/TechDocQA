"""Bounded byte inspection and handle-based local path validation."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from techdocqa.errors import TechDocQAError
from techdocqa.settings import Settings

SUPPORTED = {".pdf": "pdf", ".html": "html", ".htm": "html",
             ".md": "md", ".markdown": "md", ".txt": "txt"}
SUPPORTED_MESSAGE = "Supported: pdf, html, htm, md, markdown, txt."


@dataclass(frozen=True)
class ValidatedSource:
    path: Path
    raw_hash: str
    doc_type: str
    size_bytes: int
    page_count: int | None = None


def allowed_path(path: Path, settings: Settings) -> Path:
    if not settings.allowed_directories or any(not item.strip() for item in settings.allowed_directories):
        raise TechDocQAError("INVALID_CONFIGURATION", "Allowed directories are invalid.", stage="configuration")
    try:
        resolved = path.resolve()
        # load_settings already canonicalizes roots. Resolving them again could
        # silently authorize a different tree after an allowlisted root is swapped.
        roots = [Path(item).absolute() for item in settings.allowed_directories]
        if not any(resolved.is_relative_to(root) for root in roots):
            raise TechDocQAError("PATH_NOT_ALLOWED", "Source is outside the allowed directories.")
        return resolved
    except (OSError, ValueError, RuntimeError):
        raise TechDocQAError("SOURCE_NOT_ACCESSIBLE", "Source cannot be resolved safely.") from None


def handle_path(handle) -> Path:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt
        get_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
        get_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        get_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        size = get_path(msvcrt.get_osfhandle(handle.fileno()), buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise OSError("Cannot validate open handle")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value).resolve()
    if sys.platform.startswith("linux"):
        return Path(os.readlink(f"/proc/self/fd/{handle.fileno()}")).resolve()
    # Fail closed until another platform has an equivalent verified handle lookup.
    raise TechDocQAError("PLATFORM_NOT_SUPPORTED", "Safe handle validation is unavailable on this platform.")


def pdf_page_count(data: bytes, settings: Settings) -> int:
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-m", "techdocqa.ingestion.pdf_check"], input=data,
            capture_output=True, timeout=settings.ingestion.parse_timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        raise TechDocQAError("PARSE_TIMEOUT", "PDF preflight exceeded its time limit.", retryable=True) from None
    except OSError:
        raise TechDocQAError("PDF_CHECK_FAILED", "PDF preflight could not start.", retryable=True) from None
    if completed.returncode:
        raise TechDocQAError("PDF_CHECK_FAILED", "PDF preflight failed; verify the installed environment.", retryable=True)
    try:
        result = json.loads(completed.stdout)
        if result.get("error") == "PDF_ENCRYPTED":
            raise TechDocQAError("PDF_ENCRYPTED", "Encrypted PDFs are not supported.")
        pages = result["pages"]
        if type(pages) is not int or pages < 1:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise TechDocQAError("FORMAT_MISMATCH", "PDF structure is invalid.") from None
    if pages > settings.ingestion.max_pages:
        raise TechDocQAError("PAGE_LIMIT_EXCEEDED", "PDF exceeds the configured page limit.")
    return pages


def validate_file(path: Path, settings: Settings) -> ValidatedSource:
    resolved = allowed_path(path, settings)
    try:
        initial = resolved.stat()
        if not stat.S_ISREG(initial.st_mode):
            raise TechDocQAError("SOURCE_NOT_ACCESSIBLE", "A readable regular file is required.")
        extension = resolved.suffix.lower()
        if extension not in SUPPORTED:
            raise TechDocQAError("UNSUPPORTED_FORMAT", "File format is not supported. " + SUPPORTED_MESSAGE)
        limit = settings.ingestion.max_file_bytes
        if initial.st_size > limit:
            raise TechDocQAError("FILE_TOO_LARGE", "Source exceeds the configured byte limit.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(resolved, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            actual = allowed_path(handle_path(handle), settings)
            if (not stat.S_ISREG(opened.st_mode) or actual != resolved
                    or not os.path.samestat(initial, opened)):
                raise TechDocQAError("SOURCE_CHANGED", "Source changed during validation.", retryable=True)
            if opened.st_size > limit:
                raise TechDocQAError("FILE_TOO_LARGE", "Source exceeds the configured byte limit.")
            data = handle.read(limit + 1)
            final = os.fstat(handle.fileno())
            if len(data) > limit:
                raise TechDocQAError("FILE_TOO_LARGE", "Source exceeds the configured byte limit.")
            if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                    final.st_size, final.st_mtime_ns, final.st_ctime_ns):
                raise TechDocQAError("SOURCE_CHANGED", "Source changed while reading.", retryable=True)
            if allowed_path(handle_path(handle), settings) != actual:
                raise TechDocQAError("SOURCE_CHANGED", "Source moved while reading.", retryable=True)
    except (OSError, ValueError, RuntimeError):
        raise TechDocQAError("SOURCE_NOT_ACCESSIBLE", "Source is missing, unreadable, or unsafe.") from None
    if not data:
        raise TechDocQAError("EMPTY_FILE", "Empty files cannot be registered.")
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"Rar!", b"7z\xbc\xaf\x27\x1c")):
        raise TechDocQAError("ARCHIVE_NOT_ALLOWED", "Archives cannot be registered.")
    is_pdf = data.startswith(b"%PDF")
    if (extension == ".pdf") != is_pdf:
        raise TechDocQAError("FORMAT_MISMATCH", "File signature does not match its extension.")
    if not is_pdf and (b"\x00" in data or data.startswith((b"MZ", b"\x7fELF", b"\x89PNG", b"\xff\xd8\xff"))):
        raise TechDocQAError("FORMAT_MISMATCH", "Binary content does not match a supported text format.")
    pages = pdf_page_count(data, settings) if is_pdf else None
    return ValidatedSource(resolved, hashlib.sha256(data).hexdigest(), SUPPORTED[extension], len(data), pages)
