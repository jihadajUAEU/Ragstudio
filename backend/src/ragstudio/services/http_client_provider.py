from __future__ import annotations

import httpx


class HttpClientProvider:
    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._closed = False

    def client(self, name: str, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("HTTP client provider is closed.")
        if name not in self._clients:
            self._clients[name] = httpx.AsyncClient(timeout=timeout)
        return self._clients[name]

    async def aclose(self) -> None:
        self._closed = True
        for client in self._clients.values():
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
        self._clients.clear()
