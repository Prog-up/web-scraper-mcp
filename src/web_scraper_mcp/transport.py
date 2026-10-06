"""HTTPX adapter using HTTPcore's public connection-time network backend API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpcore
import httpx

from .config import Settings
from .security import parse_url, resolve_host


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allow_private: bool = False):
        self.allow_private = allow_private
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # noqa: ASYNC109 - HTTPcore interface
        async with asyncio.timeout(timeout):
            addresses = await resolve_host(host, port, allow_private=self.allow_private)
            # Connect only literal approved addresses. HTTPcore keeps the original
            # origin for Host, TLS SNI and certificate verification.
            error = None
            for address in addresses[:4]:
                try:
                    return await self.backend.connect_tcp(
                        address, port, timeout, local_address, socket_options
                    )
                except httpcore.ConnectError as exc:
                    error = exc
            raise httpcore.ConnectError("could not connect to approved destination") from error

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.stream:
                yield chunk
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException("response timed out") from exc
        except httpcore.NetworkError as exc:
            raise httpx.TransportError("response transport failed") from exc

    async def aclose(self):
        await self.stream.aclose()


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self, allow_private: bool = False):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=httpcore.default_ssl_context(),
            network_backend=PublicNetworkBackend(allow_private),
            max_connections=8,
            max_keepalive_connections=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        parse_url(str(request.url))
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self.pool.handle_async_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException("connection timed out") from exc
        except httpcore.NetworkError as exc:
            raise httpx.TransportError("connection failed") from exc
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=ResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


def public_client(settings: Settings) -> httpx.AsyncClient:
    """Caller-controlled destinations never inherit ambient proxy settings."""
    options: dict = {
        "trust_env": False,
        "follow_redirects": False,
        "timeout": settings.request_timeout_s,
        "headers": {"User-Agent": settings.user_agent, "Accept-Encoding": "identity"},
    }
    if settings.egress_proxy_url:
        options["proxy"] = settings.egress_proxy_url
    else:
        options["transport"] = PublicTransport(settings.allow_private_networks)
    return httpx.AsyncClient(**options)
