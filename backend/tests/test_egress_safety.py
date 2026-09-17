import asyncio
import socket
from unittest.mock import patch

from app.egress import public_web_target


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
