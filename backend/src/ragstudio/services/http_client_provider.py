from __future__ import annotations

from typing import Protocol

import httpx


class HttpClientProviderProtocol(Protocol):
    def client(self, name: str, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient: ...


class HttpClientProvider:
    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], httpx.AsyncClient] = {}
        self._closed = False

    def client(self, name: str, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("HTTP client provider is closed.")
        key = (name, repr(timeout))
        if key not in self._clients:
            self._clients[key] = httpx.AsyncClient(timeout=timeout)
        return self._clients[key]

    async def aclose(self) -> None:
        self._closed = True
        for client in self._clients.values():
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
        self._clients.clear()
