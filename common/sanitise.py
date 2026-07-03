from __future__ import annotations

import re

_MAX_QUERY_LEN = 2000

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(?:all\s+)?(?:previous|above)\s+instructions",
        r"forget\s+everything",
        r"you\s+are\s+now\s+",
        r"<script[\s>]",
        r"<!--",
        r"\bdrop\s+table\b",
        r"\bdelete\s+from\b",
        r"\binsert\s+into\b",
        r"\bexec\s*\(",
    ]
]


def sanitise_query(query: str) -> str:
    """
    Clean a user-supplied ICP query string.

    Removes control characters, enforces length limit, and raises
    ValueError on detected prompt-injection patterns.
    """
    if not isinstance(query, str):
        raise TypeError(f"Query must be a string, got {type(query).__name__}")
    query = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", query)
    query = query[:_MAX_QUERY_LEN]
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(query):
            raise ValueError(f"Query contains disallowed content matching: {pattern.pattern!r}")
    return query.strip()


def sanitise_domain(domain: str) -> str:
    """Strip protocol, path and whitespace, leaving only the hostname."""
    domain = domain.strip().lower()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    return domain.split("/")[0].split("?")[0]
