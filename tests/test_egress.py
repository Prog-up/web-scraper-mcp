"""The isolated proxy cannot inherit the app's local-testing policy bypass."""

import asyncio

import pytest

from web_scraper_mcp.config import Settings
from web_scraper_mcp.egress import EgressProxy


class Writer:
    def __init__(self):
        self.output = bytearray()
        self.closed = False

    def write(self, data):
        self.output.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


@pytest.mark.parametrize(
    "payload",
    [
        b"GET http://127.0.0.1/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: metadata\r\n\r\n",
        b"CONNECT 1.1.1.1:80 HTTP/1.1\r\nHost: public\r\n\r\n",
        b"CONNECT 1.1.1.1:443/path HTTP/1.1\r\nHost: public\r\n\r\n",
        b"TRACE http://1.1.1.1/ HTTP/1.1\r\nHost: public\r\n\r\n",
    ],
)
async def test_proxy_rejects_private_or_unsupported_requests(payload):
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    writer = Writer()
    # Even explicit local-testing settings cannot disable the proxy boundary.
    proxy = EgressProxy(Settings(_env_file=None, allow_private_networks=True))
    await proxy.handle(reader, writer)
    assert writer.output.startswith(b"HTTP/1.1 403")
    assert writer.closed
    assert proxy.slots.active == 0
