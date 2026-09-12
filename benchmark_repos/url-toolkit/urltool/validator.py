"""URL validation. Bug: any scheme://<non-empty> string is accepted even when
the host has no detectable domain/address, so 'notaurl://thing' passes."""

from __future__ import annotations

SCHEMES = ("http", "https", "ftp")


def is_valid_url(url: str) -> bool:
    """Return True when `url` looks like a usable http(s)/ftp absolute URL.

    Bug: only checks that a scheme and a non-empty remainder exist — there is
    no host validation, so 'notaurl://thing' is wrongly accepted.
    """
    if not url or " " in url:
        return False
    scheme, _, rest = url.partition("://")
    return scheme.isalpha() and len(rest) >= 1


def domain_of(url: str) -> str:
    rest = url.partition("://")[2]
    return rest.split("/")[0]