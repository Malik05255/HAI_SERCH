from unittest.mock import Mock

import app.worker as worker
from app.models import Job


def test_completed_partial_and_failed_jobs_purge_uploaded_media(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(worker, "delete_uploaded_media", lambda value: deleted.append(value) or True)
    monkeypatch.setattr(worker.settings, "notifications_enabled", False)

    for status in ("completed", "partial", "failed"):
        db = Mock()
        job = Job(status="running", input_url=f"/data/uploads/{status}.jpg")

        worker.finish_job(db, job, status)

        assert job.input_url is None
        db.commit.assert_called_once()

    assert deleted == [
        "/data/uploads/completed.jpg",
        "/data/uploads/partial.jpg",
        "/data/uploads/failed.jpg",
    ]


def test_paused_or_context_waiting_jobs_keep_media(monkeypatch) -> None:
    deleted = Mock(return_value=True)
    monkeypatch.setattr(worker, "delete_uploaded_media", deleted)
    monkeypatch.setattr(worker.settings, "notifications_enabled", False)

    for status in ("stopped", "needs_context"):
        db = Mock()
        job = Job(status="running", input_url=f"/data/uploads/{status}.jpg")

        worker.finish_job(db, job, status)

        assert job.input_url == f"/data/uploads/{status}.jpg"

    deleted.assert_not_called()
