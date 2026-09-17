from unittest.mock import Mock

from app.models import Job
from app.notifications import notification_text
import app.worker as worker


def test_completed_notification_reports_result_count() -> None:
    job = Job(status="completed", found_count=10, target_results=10)
    title, body = notification_text(job)

    assert title == "البحث العميق"
    assert "10 من 10" in body


def test_partial_notification_is_distinct() -> None:
    job = Job(status="partial", found_count=6, target_results=10)
    _, body = notification_text(job)

    assert "6 من 10" in body
    assert "موثوقة" in body


def test_needs_context_notification_requests_more_evidence() -> None:
    job = Job(status="needs_context", found_count=0, target_results=10)
    _, body = notification_text(job)

    assert "غير كافية" in body


def test_worker_pushes_only_completion_states(monkeypatch) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(worker, "send_job_pushes", lambda db, job: pushed.append(job.status) or True)

    for status in ("completed", "partial", "failed", "needs_context", "stopped"):
        db = Mock()
        job = Job(status="running", found_count=3, target_results=10)
        worker.finish_job(db, job, status)
        db.commit.assert_called_once()

    assert pushed == ["completed", "partial"]


def test_push_failure_never_breaks_completed_search(monkeypatch) -> None:
    def broken_push(_db, _job):
        raise RuntimeError("firebase unavailable")

    monkeypatch.setattr(worker, "send_job_pushes", broken_push)
    db = Mock()
    job = Job(status="running", found_count=10, target_results=10)

    worker.finish_job(db, job, "completed", 1.0)

    assert job.status == "completed"
    assert job.progress == 1.0
    db.commit.assert_called_once()
