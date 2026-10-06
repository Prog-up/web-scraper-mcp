"""SSRF guard — the #1 risk for a server that fetches arbitrary URLs.

Resolve the host and reject any URL that points at a private, loopback,
link-local (incl. cloud metadata 169.254.169.254), multicast, reserved or
unspecified address. Re-validate every redirect hop in the fetch layer.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from .limits import CapacityError

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Hostnames refused before connection-time DNS resolution.
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}
_dns_active = 0
_DNS_MAXIMUM = 32


class BlockedURLError(ValueError):
    """Raised when a URL is disallowed (bad scheme or internal address)."""


def _is_blocked_ip(ip: _IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _is_blocked_ip(ip.ipv4_mapped)
    return not ip.is_global or ip.is_multicast or ip.is_reserved


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


def parse_url(url: str) -> tuple[str, int]:
    """Validate authority/scheme without resolving DNS on the event loop."""
    if len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise BlockedURLError("invalid URL characters or length")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise BlockedURLError("invalid URL authority") from exc
    if parsed.scheme not in ("http", "https") or not host:
        raise BlockedURLError("URL must have an http(s) scheme and host")
    if parsed.username is not None or parsed.password is not None:
        raise BlockedURLError("URL credentials are not supported")
    if port == 0 or "%" in host:
        raise BlockedURLError("invalid URL port or scoped address")
    return host, port or (443 if parsed.scheme == "https" else 80)


def check_addresses(host: str, infos: list, *, allow_private: bool) -> list[str]:
    if not infos:
        raise BlockedURLError("DNS returned no addresses")
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not allow_private and any(_is_blocked_ip(ipaddress.ip_address(ip)) for ip in addresses):
        raise BlockedURLError("destination is not a public address")
    return addresses


async def resolve_host(host: str, port: int, *, allow_private: bool = False) -> list[str]:
    """Resolve once, reject mixed/private answers, return literal addresses to connect."""
    if not allow_private and host.lower().rstrip(".") in _BLOCKED_HOSTNAMES:
        raise BlockedURLError("blocked hostname")
    global _dns_active
    if _dns_active >= _DNS_MAXIMUM:
        raise CapacityError("DNS capacity reached; retry later")
    _dns_active += 1

    def finished(task):
        global _dns_active
        _dns_active -= 1
        # Retrieve errors even when the original waiter timed out.
        if not task.cancelled():
            task.exception()

    task = asyncio.create_task(
        asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    )
    task.add_done_callback(finished)
    try:
        # Retain DNS admission until the resolver actually finishes, independently
        # of a cancelled fetch or tool deadline.
        infos = await asyncio.shield(task)
    except socket.gaierror as exc:
        raise BlockedURLError("DNS resolution failed") from exc
    return check_addresses(host, infos, allow_private=allow_private)


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """Return url if safe to fetch, else raise BlockedURLError.

    Resolves DNS and rejects if *any* resolved address is internal.
    """
    host, port = parse_url(url)
    if not allow_private and host.lower().rstrip(".") in _BLOCKED_HOSTNAMES:
        raise BlockedURLError("blocked hostname")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"DNS resolution failed for {host!r}") from exc

    check_addresses(host, infos, allow_private=allow_private)
    return url
