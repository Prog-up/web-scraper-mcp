"""Internal-only HTTP proxy. Every upstream socket connects to an approved literal IP.

Never publish this port. CONNECT supports public HTTPS on port 443; ordinary HTTP
requests are bounded and decoded through the same guarded transport as scraping.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import h11
import httpx

from .config import Settings
from .limits import CapacityError, Limiter
from .security import BlockedURLError, parse_url
from .transport import PublicNetworkBackend, PublicTransport


class EgressProxy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.slots = Limiter(settings.max_concurrent_fetches * 4)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        connection = h11.Connection(h11.SERVER, max_incomplete_event_size=16_384)
        stream = None
        responded = False
        try:
            async with self.slots.slot(), asyncio.timeout(self.settings.request_timeout_s):
                request = None
                body = bytearray()
                while True:
                    event = connection.next_event()
                    if event is h11.NEED_DATA:
                        chunk = await reader.read(16_384)
                        if not chunk:
                            raise ValueError("incomplete request")
                        connection.receive_data(chunk)
                    elif isinstance(event, h11.Request):
                        request = event
                    elif isinstance(event, h11.Data):
                        if len(body) + len(event.data) > self.settings.max_request_bytes:
                            raise ValueError("request body limit")
                        body.extend(event.data)
                    elif isinstance(event, h11.EndOfMessage):
                        break
                    else:
                        raise ValueError("unexpected proxy protocol event")
                if request is None:
                    raise ValueError("missing request")
                method = request.method.decode("ascii")
                target = request.target.decode("ascii")
                if method == "CONNECT":
                    if any(char in target for char in "/?#"):
                        raise BlockedURLError("CONNECT requires a host:port authority")
                    host, port = parse_url(f"https://{target}")
                    if port != 443 or body:
                        raise BlockedURLError("only public TLS port 443 is supported")
                    stream = await PublicNetworkBackend().connect_tcp(
                        host, port, timeout=self.settings.request_timeout_s
                    )
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                    responded = True
                    trailing, _ = connection.trailing_data
                    if trailing:
                        await stream.write(trailing)

                    async def upload():
                        count = len(trailing)
                        while data := await reader.read(16_384):
                            count += len(data)
                            if count > self.settings.browser_total_bytes:
                                raise ValueError("tunnel upload limit")
                            await stream.write(data, timeout=self.settings.request_timeout_s)

                    async def download():
                        count = 0
                        while data := await stream.read(16_384, self.settings.request_timeout_s):
                            count += len(data)
                            if count > self.settings.browser_total_bytes:
                                raise ValueError("tunnel download limit")
                            writer.write(data)
                            await writer.drain()

                    tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
                    try:
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            task.result()
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    host, port = parse_url(target)
                    if port not in (80, 443) or method not in (
                        "GET",
                        "HEAD",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "OPTIONS",
                    ):
                        raise BlockedURLError("unsupported destination port or method")
                    headers = {
                        k.decode(): v.decode()
                        for k, v in request.headers
                        if k.lower()
                        not in (
                            b"host",
                            b"connection",
                            b"proxy-authorization",
                            b"proxy-connection",
                            b"content-length",
                            b"transfer-encoding",
                        )
                    }
                    headers["accept-encoding"] = "identity"
                    from .fetch import read_body

                    async with httpx.AsyncClient(
                        transport=PublicTransport(),
                        trust_env=False,
                        timeout=self.settings.request_timeout_s,
                        follow_redirects=False,
                    ) as client:
                        async with client.stream(
                            method, target, headers=headers, content=bytes(body)
                        ) as response:
                            payload = await read_body(response, self.settings.max_response_bytes)
                            response_headers = [
                                (k, v)
                                for k, v in response.headers.raw
                                if k.lower()
                                not in (
                                    b"content-length",
                                    b"connection",
                                    b"transfer-encoding",
                                    b"content-encoding",
                                )
                            ]
                            response_headers += [
                                (b"content-length", str(len(payload)).encode()),
                                (b"connection", b"close"),
                            ]
                            writer.write(
                                connection.send(
                                    h11.Response(
                                        status_code=response.status_code, headers=response_headers
                                    )
                                )
                            )
                            responded = True
                            if method != "HEAD":
                                writer.write(connection.send(h11.Data(data=payload)))
                            writer.write(connection.send(h11.EndOfMessage()))
                            await writer.drain()
        except Exception as exc:
            if not responded:
                status = 429 if isinstance(exc, CapacityError) else 502
                if isinstance(exc, (BlockedURLError, ValueError)):
                    status = 403
                writer.write(
                    (
                        f"HTTP/1.1 {status} Rejected\r\n"
                        "Content-Length: 0\r\nConnection: close\r\n\r\n"
                    ).encode()
                )
                with suppress(ConnectionError):
                    await writer.drain()
        finally:
            if stream is not None:
                with suppress(Exception):
                    await stream.aclose()
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()


async def serve():
    # Proxy policy cannot be disabled by the app's local-testing flag or .env file.
    s = Settings(_env_file=None, allow_private_networks=False, egress_proxy_url=None)
    proxy = EgressProxy(s)
    server = await asyncio.start_server(proxy.handle, s.egress_bind, 8080, limit=16_384)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())
