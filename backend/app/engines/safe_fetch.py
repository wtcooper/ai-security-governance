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
        _require_public(host, address)
    return url


# Ranges that are routable enough for `is_global` to allow but that we still refuse.
# 192.88.99.0/24 is the deprecated 6to4 relay anycast prefix and reports is_global=True.
EXTRA_DENY = (
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("2002::/16"),
    # NAT64: an embedded IPv4 address here is reachable through a translator, so a
    # well-known-prefix form can carry an internal v4 destination past a v6 check.
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


def _require_public(host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Refuse anything not globally routable.

    `is_global` rather than a hand-rolled list of predicates: an earlier version checked
    is_private/is_loopback/is_link_local/is_reserved/is_multicast/is_unspecified, which let
    100.64.0.0/10 (CGNAT) through because none of those are true of it. `is_global` is the
    property actually wanted, and it covers future non-routable assignments too.

    EXTRA_DENY then handles the cases `is_global` still allows.
    """
    narrowed = (
        # Restored after review: switching to is_global alone silently DROPPED these two,
        # which the previous predicate list did catch. No route exists in this deployment
        # (the compose network is IPv4-only and https-only blocks the plain-HTTP internal
        # services), but a fix should not quietly reduce coverage.
        address.is_multicast
        or address.is_reserved
    )
    if not address.is_global or narrowed or any(address in network for network in EXTRA_DENY):
        raise UnsafeUrlError(
            f"host {host!r} resolves to {address}, which is not a globally routable address. "
            "Refusing so this endpoint cannot be used to reach internal services, link-local "
            "metadata endpoints, or carrier-grade NAT space."
        )


async def fetch_text(url: str, timeout: float = 60.0) -> str:
    """Fetch a validated URL, pinning the address and re-validating each redirect hop.

    Validation and connection must use the SAME address. An earlier version validated the
    hostname and then handed the URL string to httpx, which resolved it again — two lookups,
    so a name whose records changed in between (DNS rebinding, TTL 0) was fetched without ever
    having been checked. Now the validated address is connected to directly, with `Host` and
    SNI preserved so TLS and virtual hosting still work.
    """
    current = validate_url(url)

    async with httpx.AsyncClient(
        timeout=timeout,
        # Redirects are followed manually so each destination is validated. Letting httpx
        # follow them would allow an allowed host to bounce us to a forbidden one.
        follow_redirects=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            pinned, host = _pin_to_validated_address(current)
            response = await client.get(
                pinned,
                headers={"User-Agent": "ai-security-governance", "Host": host},
                # Without this, TLS would be negotiated against the bare IP and fail.
                extensions={"sni_hostname": host},
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


def _pin_to_validated_address(url: str) -> tuple[str, str]:
    """Rewrite a URL to connect to a freshly validated address, returning (url, host).

    Resolving here and connecting to the literal address is what closes the gap between the
    check and the connection. The original hostname is returned so the caller can restore it
    as the Host header and SNI name.
    """
    parsed = httpx.URL(url)
    host = parsed.host
    address = _addresses_for(host)[0]
    _require_public(host, address)
    literal = f"[{address}]" if address.version == 6 else str(address)
    return str(parsed.copy_with(host=literal)), host
