from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, engine, ensure_schema
from app.server import app


def _wipe_database() -> None:
    ensure_schema()
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture(autouse=True)
def isolated_state():
    _wipe_database()
    shutil.rmtree(Path(settings.data_dir), ignore_errors=True)
    yield
    _wipe_database()
    shutil.rmtree(Path(settings.data_dir), ignore_errors=True)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def linked_devices(client):
    android = client.post("/v1/auth/register", json={"name": "Android"})
    assert android.status_code == 200
    android_data = android.json()
    android_headers = {"Authorization": f"Bearer {android_data['token']}"}

    code = client.post("/v1/auth/pair-code", headers=android_headers)
    assert code.status_code == 200

    windows = client.post(
        "/v1/auth/pair",
        json={"code": code.json()["code"], "name": "Windows"},
    )
    assert windows.status_code == 200
    windows_data = windows.json()
    windows_headers = {"Authorization": f"Bearer {windows_data['token']}"}

    return {
        "android": android_data,
        "android_headers": android_headers,
        "windows": windows_data,
        "windows_headers": windows_headers,
    }
