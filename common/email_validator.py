from __future__ import annotations

from collections.abc import Iterable
import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_DISPOSABLE = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "10minutemail.com",
        "throwam.com",
        "trashmail.com",
        "yopmail.com",
        "temp-mail.org",
        "sharklasers.com",
        "guerrillamailblock.com",
        "grr.la",
        "spam4.me",
        "maildrop.cc",
        "dispostable.com",
    }
)

_JUNK_PATTERNS = (
    re.compile(r"\.(png|jpg|gif|css|js|svg|ico)$", re.IGNORECASE),
    re.compile(r"example\.(com|org|net)$", re.IGNORECASE),
    re.compile(r"@sentry\.io$", re.IGNORECASE),
    re.compile(r"@.*\.(woff|ttf|eot)$", re.IGNORECASE),
)


def is_valid_email(email: str) -> bool:
    """Return True if email passes format + disposable domain checks."""
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return False
    domain = email.split("@", 1)[1]
    if domain in _DISPOSABLE:
        return False
    return not any(p.search(domain) for p in _JUNK_PATTERNS)


def filter_valid(emails: Iterable[str]) -> list[str]:
    """Return only valid, unique emails preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for e in emails:
        clean = e.strip().lower()
        if clean not in seen and is_valid_email(clean):
            seen.add(clean)
            result.append(clean)
    return result
