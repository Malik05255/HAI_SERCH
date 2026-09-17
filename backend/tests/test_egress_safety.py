import asyncio
import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import settings
from app.egress import EgressRouter, parse_proxy_profiles, public_web_target


def run(url: str) -> bool:
    return asyncio.run(public_web_target(url))


def test_rejects_private_loopback_and_non_web_ports() -> None:
    assert not run("http://127.0.0.1/")
    assert not run("http://10.0.0.2/")
    assert not run("http://169.254.169.254/latest/meta-data/")
    assert not run("http://localhost/")
    assert not run("http://example.com:8080/")
    assert run("https://8.8.8.8/")


def test_rejects_hostname_when_dns_resolves_private() -> None:
    private_dns = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443)),
    ]
    with patch("app.egress.socket.getaddrinfo", return_value=private_dns):
        assert not run("https://example.test/")


def test_accepts_hostname_when_all_dns_answers_are_public() -> None:
    public_dns = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ]
    with patch("app.egress.socket.getaddrinfo", return_value=public_dns):
        assert run("https://example.test/")


def test_named_proxy_profiles_keep_legacy_vpn_and_reject_invalid_entries() -> None:
    profiles = parse_proxy_profiles(
        "http://vpn-default:8888",
        "asia=http://vpn-asia:8888; europe=https://vpn-eu:8443, direct=http://bad:1, bad name=http://bad:2",
    )

    assert profiles == {
        "vpn": "http://vpn-default:8888",
        "asia": "http://vpn-asia:8888",
        "europe": "https://vpn-eu:8443",
    }


def test_router_rejects_redirect_to_private_target_before_second_request() -> None:
    async def scenario() -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                request=request,
            )

        router = EgressRouter(timeout=httpx.Timeout(5.0), headers={"User-Agent": "test"})
        await router._direct.aclose()
        router._direct = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        router._target_allowed = AsyncMock(
            side_effect=lambda url: not url.startswith("http://127.0.0.1")
        )
        try:
            with pytest.raises(httpx.InvalidURL):
                await router.get("https://example.test/start")
        finally:
            await router._direct.aclose()
            for client in router._proxies.values():
                await client.aclose()

        assert seen == ["https://example.test/start"]

    asyncio.run(scenario())


def test_router_allows_safe_relative_public_redirect() -> None:
    async def scenario() -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path == "/start":
                return httpx.Response(302, headers={"location": "/next"}, request=request)
            return httpx.Response(200, text="ok", request=request)

        router = EgressRouter(timeout=httpx.Timeout(5.0), headers={"User-Agent": "test"})
        await router._direct.aclose()
        router._direct = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        router._target_allowed = AsyncMock(return_value=True)
        try:
            response = await router.get("https://example.test/start")
        finally:
            await router._direct.aclose()
            for client in router._proxies.values():
                await client.aclose()

        assert response.status_code == 200
        assert seen == [
            "https://example.test/start",
            "https://example.test/next",
        ]

    asyncio.run(scenario())


def test_network_failure_can_fall_back_to_named_server_exit(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(settings, "egress_mode", "auto")
        monkeypatch.setattr(settings, "egress_proxy_url", "")
        monkeypatch.setattr(settings, "egress_proxy_urls", "asia=http://vpn-asia:8888")

        proxy_seen = 0

        def direct_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("direct unavailable", request=request)

        def proxy_handler(request: httpx.Request) -> httpx.Response:
            nonlocal proxy_seen
            proxy_seen += 1
            return httpx.Response(200, text="ok", request=request)

        router = EgressRouter(timeout=httpx.Timeout(5.0), headers={"User-Agent": "test"})
        await router._direct.aclose()
        old_proxy = router._proxies["asia"]
        await old_proxy.aclose()
        router._direct = httpx.AsyncClient(transport=httpx.MockTransport(direct_handler))
        router._proxies["asia"] = httpx.AsyncClient(transport=httpx.MockTransport(proxy_handler))
        router._target_allowed = AsyncMock(return_value=True)
        try:
            response = await router.get("https://example.test/item")
            assert response.status_code == 200
            assert router._sticky["example.test"] == "asia"
            assert proxy_seen == 1
        finally:
            await router._direct.aclose()
            await router._proxies["asia"].aclose()

    asyncio.run(scenario())


def test_http_429_never_rotates_to_another_exit(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(settings, "egress_mode", "auto")
        monkeypatch.setattr(settings, "egress_proxy_url", "")
        monkeypatch.setattr(settings, "egress_proxy_urls", "europe=http://vpn-europe:8888")

        proxy_seen = 0

        def direct_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited", request=request)

        def proxy_handler(request: httpx.Request) -> httpx.Response:
            nonlocal proxy_seen
            proxy_seen += 1
            return httpx.Response(200, text="should not run", request=request)

        router = EgressRouter(timeout=httpx.Timeout(5.0), headers={"User-Agent": "test"})
        await router._direct.aclose()
        old_proxy = router._proxies["europe"]
        await old_proxy.aclose()
        router._direct = httpx.AsyncClient(transport=httpx.MockTransport(direct_handler))
        router._proxies["europe"] = httpx.AsyncClient(transport=httpx.MockTransport(proxy_handler))
        router._target_allowed = AsyncMock(return_value=True)
        try:
            with pytest.raises(httpx.HTTPStatusError) as error:
                await router.get("https://example.test/item")
            assert error.value.response.status_code == 429
            assert proxy_seen == 0
        finally:
            await router._direct.aclose()
            await router._proxies["europe"].aclose()

    asyncio.run(scenario())
