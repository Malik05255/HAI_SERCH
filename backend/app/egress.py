from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from collections import defaultdict
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
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_global
    except ValueError:
        return False


def _valid_proxy_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def parse_proxy_profiles(primary: str, extras: str) -> dict[str, str]:
    """Parse backward-compatible server proxy exits.

    `EGRESS_PROXY_URL` remains the `vpn` profile. `EGRESS_PROXY_URLS` accepts
    comma/semicolon separated `name=http://proxy:port` entries. Invalid profile
    names/URLs are ignored rather than handed to httpx.
    """
    profiles: dict[str, str] = {}
    primary = primary.strip()
    if primary and _valid_proxy_url(primary):
        profiles["vpn"] = primary

    for entry in re.split(r"[;,]", extras):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        name, value = (part.strip() for part in entry.split("=", 1))
        name = name.casefold()
        if name == "direct" or not _PROFILE_NAME_RE.fullmatch(name):
            continue
        if not _valid_proxy_url(value):
            continue
        profiles.setdefault(name, value)
    return profiles


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
    """Route public web requests through direct or server-side proxy exits.

    Every redirect target is validated before the next request so a public URL
    cannot redirect the worker into loopback/private/link-local space.

    In `auto` mode a successful route stays sticky for the original host. A
    route switch is allowed only for transport failures or HTTP 451. 403/429
    and application-level denials never trigger another exit. Repeated transport
    failures temporarily open a small circuit breaker for that route.
    """

    def __init__(self, *, timeout: httpx.Timeout, headers: dict[str, str]):
        mode = settings.egress_mode.strip().lower()
        if mode not in {"auto", "direct", "vpn"}:
            mode = "auto"
        self.mode = mode
        self.proxy_profiles = parse_proxy_profiles(
            settings.egress_proxy_url,
            settings.egress_proxy_urls,
        )
        self._sticky: dict[str, str] = {}
        self._safe_targets: dict[tuple[str, int | None], bool] = {}
        self._failure_streak: defaultdict[str, int] = defaultdict(int)
        self._blocked_until: dict[str, float] = {}
        self._direct = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False)
        self._proxies = {
            name: httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=False,
                proxy=url,
            )
            for name, url in self.proxy_profiles.items()
        }
        # Compatibility for existing diagnostics/tests referring to `_vpn`.
        self._vpn = self._proxies.get("vpn")

    async def __aenter__(self) -> "EgressRouter":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._direct.aclose()
        for client in self._proxies.values():
            await client.aclose()

    def _route_is_open(self, route: str) -> bool:
        blocked_until = self._blocked_until.get(route, 0.0)
        return blocked_until <= time.monotonic()

    def _record_success(self, route: str) -> None:
        self._failure_streak.pop(route, None)
        self._blocked_until.pop(route, None)

    def _record_transport_failure(self, route: str) -> None:
        streak = self._failure_streak[route] + 1
        self._failure_streak[route] = streak
        if streak >= 2:
            cooldown = min(60.0, 5.0 * (2 ** min(streak - 2, 4)))
            self._blocked_until[route] = time.monotonic() + cooldown

    def _routes(self, url: str) -> list[str]:
        host = (urlparse(url).hostname or "").casefold()
        if self.mode == "direct":
            return ["direct"]

        proxy_routes = list(self._proxies)
        if self.mode == "vpn":
            if not proxy_routes:
                raise RuntimeError("EGRESS_MODE=vpn requires EGRESS_PROXY_URL or EGRESS_PROXY_URLS")
            available = [route for route in proxy_routes if self._route_is_open(route)]
            return available or proxy_routes

        available = ["direct", *proxy_routes]
        healthy = [route for route in available if self._route_is_open(route)]
        if healthy:
            available = healthy

        sticky = self._sticky.get(host)
        if sticky in available:
            return [sticky] + [route for route in available if route != sticky]
        return available

    def _client(self, route: str) -> httpx.AsyncClient:
        if route == "direct":
            return self._direct
        client = self._proxies.get(route)
        if client is None:
            raise RuntimeError(f"egress route is unavailable: {route}")
        return client

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

    async def _validated_read_limited(
        self,
        client: httpx.AsyncClient,
        url: str,
        max_bytes: int,
    ) -> tuple[httpx.Response, bytes]:
        current = url

        for redirect_count in range(_MAX_REDIRECTS + 1):
            if not await self._target_allowed(current):
                raise httpx.InvalidURL("public web egress target required")

            request = client.build_request("GET", current)
            response = await client.send(request, stream=True, follow_redirects=False)

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    return response, b""
                if redirect_count >= _MAX_REDIRECTS:
                    raise httpx.TooManyRedirects(
                        "too many public web redirects",
                        request=response.request,
                    )
                current = urljoin(str(response.url), location)
                continue

            if response.status_code >= 400:
                await response.aclose()
                return response, b""

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        await response.aclose()
                        raise ValueError("response_too_large")
                except ValueError as exc:
                    if str(exc) == "response_too_large":
                        raise

            chunks: list[bytes] = []
            total = 0
            try:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("response_too_large")
                    chunks.append(chunk)
            finally:
                await response.aclose()
            return response, b"".join(chunks)

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
                self._record_success(route)
                if host:
                    self._sticky[host] = route
                return response
            except _NETWORK_ERRORS as exc:
                last_error = exc
                self._record_transport_failure(route)
                if index + 1 < len(routes):
                    continue
                raise
            except httpx.HTTPStatusError:
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("no egress route available")

    async def get_bytes(self, url: str, *, max_bytes: int) -> tuple[httpx.Response, bytes]:
        """Fetch bounded public bytes using the same validated egress policy."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not await self._target_allowed(url):
            raise httpx.InvalidURL("public web egress target required")

        host = (urlparse(url).hostname or "").casefold()
        routes = self._routes(url)
        last_error: Exception | None = None

        for index, route in enumerate(routes):
            client = self._client(route)
            try:
                response, body = await self._validated_read_limited(client, url, max_bytes)
                if response.status_code == 451 and index + 1 < len(routes):
                    last_error = httpx.HTTPStatusError(
                        "Unavailable For Legal Reasons",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                self._record_success(route)
                if host:
                    self._sticky[host] = route
                return response, body
            except _NETWORK_ERRORS as exc:
                last_error = exc
                self._record_transport_failure(route)
                if index + 1 < len(routes):
                    continue
                raise
            except (httpx.HTTPStatusError, ValueError):
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("no egress route available")
