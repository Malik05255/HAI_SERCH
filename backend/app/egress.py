from __future__ import annotations

from urllib.parse import urlparse

import httpx

from .config import settings


_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class EgressRouter:
    """Route public web requests through direct or VPN-backed proxy egress.

    Internal services such as SearXNG must use their own direct Docker-network
    client and never pass through this router. In auto mode we prefer a sticky
    successful route for each host. A route switch happens only for transport
    failures or HTTP 451; 403/429/CAPTCHA-like responses are deliberately not
    treated as a reason to rotate egress.
    """

    def __init__(self, *, timeout: httpx.Timeout, headers: dict[str, str]):
        mode = settings.egress_mode.strip().lower()
        if mode not in {"auto", "direct", "vpn"}:
            mode = "auto"
        self.mode = mode
        self.proxy_url = settings.egress_proxy_url.strip() or None
        self._sticky: dict[str, str] = {}
        self._direct = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)
        self._vpn = (
            httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, proxy=self.proxy_url)
            if self.proxy_url
            else None
        )

    async def __aenter__(self) -> "EgressRouter":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._direct.aclose()
        if self._vpn is not None:
            await self._vpn.aclose()

    def _routes(self, url: str) -> list[str]:
        host = (urlparse(url).hostname or "").casefold()
        if self.mode == "direct":
            return ["direct"]
        if self.mode == "vpn":
            if self._vpn is None:
                raise RuntimeError("EGRESS_MODE=vpn requires EGRESS_PROXY_URL")
            return ["vpn"]

        sticky = self._sticky.get(host)
        available = ["direct"] + (["vpn"] if self._vpn is not None else [])
        if sticky in available:
            return [sticky] + [route for route in available if route != sticky]
        return available

    def _client(self, route: str) -> httpx.AsyncClient:
        if route == "vpn":
            if self._vpn is None:
                raise RuntimeError("VPN egress is unavailable")
            return self._vpn
        return self._direct

    async def get(self, url: str, **kwargs) -> httpx.Response:
        host = (urlparse(url).hostname or "").casefold()
        routes = self._routes(url)
        last_error: Exception | None = None

        for index, route in enumerate(routes):
            client = self._client(route)
            try:
                response = await client.get(url, **kwargs)
                # 451 represents legal/geographic unavailability and is the one
                # HTTP status for which auto mode may try the alternate egress.
                if response.status_code == 451 and index + 1 < len(routes):
                    last_error = httpx.HTTPStatusError(
                        "Unavailable For Legal Reasons",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                if host:
                    self._sticky[host] = route
                return response
            except _NETWORK_ERRORS as exc:
                last_error = exc
                if index + 1 < len(routes):
                    continue
                raise
            except httpx.HTTPStatusError:
                # Do not rotate on 403/429 or other application-level denials.
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("no egress route available")
