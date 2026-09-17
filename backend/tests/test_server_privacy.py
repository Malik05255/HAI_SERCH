import pytest
from fastapi import HTTPException

import app.server as server
from app.models import Job


def test_terminal_media_job_cannot_be_reopened_after_purge(monkeypatch) -> None:
    monkeypatch.setattr(server, "_media_path", lambda _job, _account: None)
    job = Job(status="completed", input_type="video", input_url=None)

    with pytest.raises(HTTPException) as error:
        server._ensure_clue_can_reopen(job, "account-1")

    assert error.value.status_code == 409
    assert "upload it again" in str(error.value.detail)


def test_text_job_can_be_reopened_without_media(monkeypatch) -> None:
    monkeypatch.setattr(server, "_media_path", lambda _job, _account: None)
    job = Job(status="completed", input_type="text", input_url=None)

    server._ensure_clue_can_reopen(job, "account-1")


def test_paused_media_job_is_not_blocked_by_terminal_guard(monkeypatch) -> None:
    monkeypatch.setattr(server, "_media_path", lambda _job, _account: None)
    job = Job(status="stopped", input_type="image", input_url=None)

    server._ensure_clue_can_reopen(job, "account-1")
