import asyncio
import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.egress import EgressRouter, public_web_target


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

        assert response.status_code == 200
        assert seen == [
            "https://example.test/start",
            "https://example.test/next",
        ]

    asyncio.run(scenario())
