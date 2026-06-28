"""SSRF guard — the critical security check. Uses IP literals so no network/DNS."""

import pytest

from web_scraper_mcp.security import (
    BlockedURLError,
    host_is_obviously_private,
    validate_url,
)

BLOCKED = [
    "http://127.0.0.1/",
    "http://localhost/admin",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.5/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://0.0.0.0/",
    "ftp://example.com/",  # bad scheme
    "file:///etc/passwd",  # bad scheme
    "http:///nohost",  # missing host
]


@pytest.mark.parametrize("url", BLOCKED)
def test_blocks_internal_and_bad_schemes(url):
    with pytest.raises(BlockedURLError):
        validate_url(url)


@pytest.mark.parametrize("url", ["http://1.1.1.1/", "https://8.8.8.8/"])
def test_allows_public_ip_literals(url):
    assert validate_url(url) == url


def test_allow_private_flag_bypasses():
    assert validate_url("http://127.0.0.1/", allow_private=True)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("169.254.169.254", True),
        ("::1", True),
        ("8.8.8.8", False),
        ("example.com", False),  # a name — not resolved by this cheap check
    ],
)
def test_host_is_obviously_private(host, expected):
    assert host_is_obviously_private(host) is expected
