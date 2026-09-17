#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
PLACEHOLDER_WORDS = ("replace-with", "change-me", "example.com", "deepsearch_local")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid env line: {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("empty env key")
        values[key] = value.strip().strip('"').strip("'")
    return values


def fail(message: str) -> None:
    raise ValueError(message)


def validate(values: dict[str, str], *, example: bool = False) -> None:
    if values.get("APP_ENV") != "production":
        fail("APP_ENV must be production")

    host = values.get("PUBLIC_HOST", "")
    if not host or not HOST_RE.fullmatch(host) or ".." in host:
        fail("PUBLIC_HOST must be a hostname without scheme/path")

    public_url = values.get("PUBLIC_BASE_URL", "")
    parsed = urlsplit(public_url)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.path not in ("", "/"):
        fail("PUBLIC_BASE_URL must be https://PUBLIC_HOST with no path")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        fail("PUBLIC_BASE_URL must not contain credentials, query, or fragment")

    password = values.get("POSTGRES_PASSWORD", "")
    if len(password) < 24:
        fail("POSTGRES_PASSWORD must be at least 24 characters")

    if not example:
        lowered = " ".join((host, public_url, password)).casefold()
        if any(word in lowered for word in PLACEHOLDER_WORDS):
            fail("production env still contains placeholder/default values")

    if values.get("NOTIFICATIONS_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}:
        project = values.get("FIREBASE_PROJECT_ID", "")
        account = values.get("FIREBASE_SERVICE_ACCOUNT_B64", "")
        if not project or not account:
            fail("Firebase project/service-account are required when notifications are enabled")
        if not example:
            try:
                decoded = base64.b64decode(account, validate=True)
            except Exception as exc:
                raise ValueError("FIREBASE_SERVICE_ACCOUNT_B64 is not valid base64") from exc
            if b'"private_key"' not in decoded or b'"client_email"' not in decoded:
                fail("Firebase service account payload is incomplete")

    mode = values.get("EGRESS_MODE", "auto")
    if mode not in {"auto", "direct", "vpn"}:
        fail("EGRESS_MODE must be auto, direct, or vpn")

    repo = values.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        fail("GITHUB_REPOSITORY must be owner/repository")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--example", action="store_true")
    args = parser.parse_args()

    try:
        values = load_env(args.env_file)
        validate(values, example=args.example)
    except (OSError, ValueError) as exc:
        print(f"production env invalid: {exc}", file=sys.stderr)
        return 1

    print("production env valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
