from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

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
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_global
    except ValueError:
        return False


async def public_web_target(url: str) -> bool:
    """Allow only normal public HTTP(S) destinations used for web research."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        port = parsed.port
    except ValueError:
        return False

    if port not in {None, 80, 443}:
        return False

    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False

    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
        return literal.is_global
    except ValueError:
        pass

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port or (443 if parsed.scheme == "https" else 80),
            0,
            socket.SOCK_STREAM,
        )
    except OSError:
        return False

    addresses = {info[4][0].split("%", 1)[0] for info in infos if info[4]}
    return bool(addresses) and all(_public_ip(address) for address in addresses)


class EgressRouter:
    """Route public web requests through direct or VPN-backed proxy egress.

    Every redirect target is validated before the next request so a public URL
    cannot redirect the research worker into loopback/private/link-local space.
    In auto mode a successful route remains sticky per original host. Route
    switching happens only for transport failures or HTTP 451, never for
    application-level denials such as 403/429/CAPTCHA pages.
    """

    def __init__(self, *, timeout: httpx.Timeout, headers: dict[str, str]):
        mode = settings.egress_mode.strip().lower()
        if mode not in {"auto", "direct", "vpn"}:
            mode = "auto"
        self.mode = mode
        self.proxy_url = settings.egress_proxy_url.strip() or None
        self._sticky: dict[str, str] = {}
        self._safe_targets: dict[tuple[str, int | None], bool] = {}
        self._direct = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False)
        self._vpn = (
            httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False, proxy=self.proxy_url)
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

    async def _target_allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            key = ((parsed.hostname or "").casefold(), parsed.port)
        except ValueError:
            return False
        if key not in self._safe_targets:
            self._safe_targets[key] = await public_web_target(url)
        return self._safe_targets[key]

    async def _validated_get(self, client: httpx.AsyncClient, url: str, kwargs: dict) -> httpx.Response:
        current = url
        request_kwargs = dict(kwargs)
        request_kwargs["follow_redirects"] = False

        for redirect_count in range(_MAX_REDIRECTS + 1):
            if not await self._target_allowed(current):
                raise httpx.InvalidURL("public web egress target required")

            response = await client.get(current, **request_kwargs)
            if response.status_code not in _REDIRECT_STATUSES:
                return response

            location = response.headers.get("location")
            if not location:
                return response
            if redirect_count >= _MAX_REDIRECTS:
                raise httpx.TooManyRedirects(
                    "too many public web redirects",
                    request=response.request,
                )
            current = urljoin(str(response.url), location)

        raise RuntimeError("redirect handling exhausted")

    async def get(self, url: str, **kwargs) -> httpx.Response:
        if not await self._target_allowed(url):
            raise httpx.InvalidURL("public web egress target required")

        host = (urlparse(url).hostname or "").casefold()
        routes = self._routes(url)
        last_error: Exception | None = None

        for index, route in enumerate(routes):
            client = self._client(route)
            try:
                response = await self._validated_get(client, url, kwargs)
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
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("no egress route available")
