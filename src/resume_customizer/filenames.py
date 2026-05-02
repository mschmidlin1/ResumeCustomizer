"""Filesystem-safe basename helpers for download filenames."""

from __future__ import annotations

import re
import time
import unicodedata

# Windows reserved device names (without extension).
_WINDOWS_RESERVED: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
)

_MAX_BASE_LEN: int = 120

# ``_`` + 7 base-36 digits (zero-padded Unix second).
_DISAMBIGUATION_SUFFIX_CHARS: int = 7
_DOWNLOAD_DISAMBIGUATION_EXTRA: int = 1 + _DISAMBIGUATION_SUFFIX_CHARS

_BASE36_ALPHABET: str = "0123456789abcdefghijklmnopqrstuvwxyz"

#: Default basename used when the title is empty or unusable (public for callers).
DEFAULT_FILENAME_BASE: str = "resume_customized"

_FALLBACK_BASE: str = DEFAULT_FILENAME_BASE


def safe_filename_base(title: str, *, max_len: int = _MAX_BASE_LEN) -> str:
    """Normalize arbitrary text into a safe single-segment filename stem.

    Strips control characters, collapses whitespace, removes characters unsafe on
    Windows and POSIX, avoids trailing dots/spaces (Windows), and caps length.
    If the result is empty or a reserved Windows device name, returns a fallback.

    Args:
        title: Raw title or label (e.g. job title from the model).
        max_len: Maximum length of the returned basename (excluding extension).

    Returns:
        A non-empty string safe to use as ``{base}.tex`` / ``{base}.pdf``.
    """
    if not title or not str(title).strip():
        return _FALLBACK_BASE

    normalized = unicodedata.normalize("NFKC", str(title))
    # Remove control characters and NULL.
    normalized = "".join(ch for ch in normalized if ch.isprintable() and ch != "\x00")
    normalized = normalized.strip()
    if not normalized:
        return _FALLBACK_BASE

    # Replace path separators and forbidden characters.
    normalized = re.sub(r'[<>:"/\\|?*]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip(" .")

    normalized = normalized[:max_len].rstrip(" .")
    if not normalized:
        return _FALLBACK_BASE

    upper = normalized.upper()
    if upper in _WINDOWS_RESERVED or upper.split(".")[0] in _WINDOWS_RESERVED:
        return _FALLBACK_BASE

    return normalized


def _int_to_base36_padded(n: int, width: int) -> str:
    if n < 0:
        raise ValueError("timestamp must be non-negative")
    if n == 0:
        return "0" * width
    digits: list[str] = []
    x = n
    while x:
        digits.append(_BASE36_ALPHABET[x % 36])
        x //= 36
    body = "".join(reversed(digits))
    if len(body) > width:
        body = body[-width:]
    return body.rjust(width, "0")


def download_disambiguation_suffix(now: float | None = None) -> str:
    """Build a short ``_`` + base-36 Unix-second tag for download stems.

    Fixed width preserves lexicographic sort order matching time order.

    Args:
        now: Optional epoch seconds (for tests); defaults to :func:`time.time`.

    Returns:
        Eight characters: underscore plus seven ``0-9a-z`` digits.
    """
    ts = int(now if now is not None else time.time())
    return "_" + _int_to_base36_padded(ts, _DISAMBIGUATION_SUFFIX_CHARS)


def with_download_disambiguation(
    stem: str,
    *,
    now: float | None = None,
    max_len: int = _MAX_BASE_LEN,
) -> str:
    """Append :func:`download_disambiguation_suffix`, keeping total stem within ``max_len``."""
    suffix = download_disambiguation_suffix(now)
    cap = max_len - _DOWNLOAD_DISAMBIGUATION_EXTRA
    if cap < 1:
        raise ValueError("max_len must exceed disambiguation suffix length")
    base = stem
    if len(base) > cap:
        base = base[:cap].rstrip(" .")
    if not base:
        base = _FALLBACK_BASE
    return f"{base}{suffix}"
