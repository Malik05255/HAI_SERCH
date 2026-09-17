from unittest.mock import Mock

import app.notifications as notifications
import app.worker as worker
from app.models import Job
from app.notifications import notification_text


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
    monkeypatch.setattr(worker.settings, "notifications_enabled", True)
    monkeypatch.setattr(worker, "send_job_pushes", lambda db, job: pushed.append(job.status) or True)

    for status in ("completed", "partial", "failed", "needs_context", "stopped"):
        db = Mock()
        job = Job(status="running", found_count=3, target_results=10)
        worker.finish_job(db, job, status)

        if status in {"completed", "partial"}:
            assert job.notification_pending is False
            assert job.notification_sent_at is not None
            assert db.commit.call_count == 2
        else:
            assert job.notification_pending is False
            assert db.commit.call_count == 1

    assert pushed == ["completed", "partial"]


def test_push_failure_stays_pending_without_breaking_search(monkeypatch) -> None:
    def broken_push(_db, _job):
        raise RuntimeError("firebase unavailable")

    monkeypatch.setattr(worker.settings, "notifications_enabled", True)
    monkeypatch.setattr(worker, "send_job_pushes", broken_push)
    db = Mock()
    job = Job(status="running", found_count=10, target_results=10)

    worker.finish_job(db, job, "completed", 1.0)

    assert job.status == "completed"
    assert job.progress == 1.0
    assert job.notification_pending is True
    assert job.notification_sent_at is None
    db.commit.assert_called_once()


def test_notifications_disabled_do_not_create_pending_delivery(monkeypatch) -> None:
    sender = Mock(return_value=True)
    monkeypatch.setattr(worker.settings, "notifications_enabled", False)
    monkeypatch.setattr(worker, "send_job_pushes", sender)
    db = Mock()
    job = Job(status="running", found_count=10, target_results=10)

    worker.finish_job(db, job, "completed", 1.0)

    assert job.notification_pending is False
    sender.assert_not_called()
    db.commit.assert_called_once()


def test_enabled_notifications_with_missing_firebase_credentials_stay_pending(monkeypatch) -> None:
    monkeypatch.setattr(notifications.settings, "notifications_enabled", True)
    monkeypatch.setattr(notifications, "_firebase_credentials", lambda: None)
    db = Mock()
    job = Job(account_id="account-1", status="completed", found_count=10, target_results=10)

    assert notifications.send_job_pushes(db, job) is False
