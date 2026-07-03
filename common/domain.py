from __future__ import annotations

from urllib.parse import urlparse

_STRIP_PREFIXES = (
    "www.",
    "mail.",
    "app.",
    "jobs.",
    "careers.",
    "blog.",
    "shop.",
    "help.",
    "support.",
    "api.",
)


def normalise_domain(url_or_domain: str) -> str:
    """Extract canonical bare domain (no www, no port, no path)."""
    s = url_or_domain.strip().lower()
    if "://" in s:
        try:
            netloc = urlparse(s).netloc or s
            s = netloc
        except Exception:
            pass
    s = s.split(":")[0]
    for prefix in _STRIP_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return s.strip(".")


def domains_match(a: str, b: str) -> bool:
    """Return True if two URLs / domain strings resolve to the same domain."""
    return normalise_domain(a) == normalise_domain(b)


def extract_root_domain(url: str) -> str:
    """Return the eTLD+1 portion (e.g. 'sub.acme.co.uk' → 'acme.co.uk')."""
    domain = normalise_domain(url)
    parts = domain.split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3:  # e.g. co.uk, com.au
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain
