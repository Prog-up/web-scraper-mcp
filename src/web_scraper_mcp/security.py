"""SSRF guard — the #1 risk for a server that fetches arbitrary URLs.

Resolve the host and reject any URL that points at a private, loopback,
link-local (incl. cloud metadata 169.254.169.254), multicast, reserved or
unspecified address. Re-validate every redirect hop in the fetch layer.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Hostnames we refuse without even resolving (defence in depth for the browser
# route filter, which can't afford a DNS lookup per subresource).
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class BlockedURLError(ValueError):
    """Raised when a URL is disallowed (bad scheme or internal address)."""


def _is_blocked_ip(ip: _IPAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def host_is_obviously_private(host: str) -> bool:
    """Cheap, no-DNS check: blocked hostname or an IP literal that is internal.

    Used by the Playwright route filter on every subresource request.
    """
    host = host.strip("[]").lower()
    if host in _BLOCKED_HOSTNAMES:
        return True
    try:
        return _is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        return False  # not an IP literal — a name we don't resolve here


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """Return url if safe to fetch, else raise BlockedURLError.

    Resolves DNS and rejects if *any* resolved address is internal.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("URL has no host")
    if allow_private:
        return url
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise BlockedURLError(f"blocked host {host!r}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"DNS resolution failed for {host!r}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise BlockedURLError(f"blocked internal address {ip} for host {host!r}")
    return url
