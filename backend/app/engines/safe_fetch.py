"""Fetching a user-supplied URL without turning the server into a proxy for its own network.

The published-score flow takes a URL from the client and fetches it server-side, which is the
textbook setup for SSRF: `http://169.254.169.254/` reaches cloud instance metadata,
`http://localhost:8000/` reaches this very API, and `http://gateway:4000/` reaches the model
gateway. "It's an internal tool" is not a defence — internal services are the usual target.

Three controls, all necessary:

1. **https only.** No `file://`, no `gopher://`, no non-standard ports over cleartext.
2. **Resolve the hostname and check every address.** A name like `metadata.example.com` can
   resolve to 169.254.169.254, so validating the string is not enough.
3. **Do not follow redirects.** A permitted host can redirect to a forbidden one, so each hop
   is re-validated explicitly instead of trusting the client library.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_REDIRECTS = 3
MAX_BYTES = 5 * 1024 * 1024


class UnsafeUrlError(Exception):
    """Raised when a URL is not safe to fetch server-side."""


def _addresses_for(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host {host!r}: {exc}") from exc
    addresses = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise UnsafeUrlError(f"host {host!r} resolved to no usable address")
    return addresses


def validate_url(url: str) -> str:
    """Reject anything that is not a public https endpoint."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeUrlError(
            f"URL must be https, got {parsed.scheme or 'no scheme'!r}. Fetching other schemes "
            "server-side would let a submission reach the local filesystem or internal ports."
        )
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

    for address in _addresses_for(host):
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeUrlError(
                f"host {host!r} resolves to {address}, which is a private, loopback, or "
                "link-local address. Refusing so this endpoint cannot be used to reach "
                "internal services or cloud instance metadata."
            )
    return url


async def fetch_text(url: str, timeout: float = 60.0) -> str:
    """Fetch a validated URL, re-validating each redirect hop by hand."""
    current = validate_url(url)

    async with httpx.AsyncClient(
        timeout=timeout,
        # Redirects are followed manually so each destination is validated. Letting httpx
        # follow them would allow an allowed host to bounce us to a forbidden one.
        follow_redirects=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(
                current, headers={"User-Agent": "ai-security-governance"}
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeUrlError("redirect without a Location header")
                current = validate_url(str(httpx.URL(current).join(location)))
                continue
            response.raise_for_status()
            return response.text[:MAX_BYTES]

    raise UnsafeUrlError(f"more than {MAX_REDIRECTS} redirects")
