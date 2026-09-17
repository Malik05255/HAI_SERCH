from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.notifications as notifications
import app.worker as worker
from app.database import Base
from app.models import Account, Device, Job, NotificationDelivery
from app.notifications import notification_text


def _memory_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_notification_job(db: Session) -> Job:
    account = Account(id="account-1")
    device_a = Device(
        id="device-a",
        account_id=account.id,
        name="Android",
        token_hash="hash-a",
        push_token="token-a",
    )
    device_b = Device(
        id="device-b",
        account_id=account.id,
        name="Android 2",
        token_hash="hash-b",
        push_token="token-b",
    )
    job = Job(
        id="job-1",
        account_id=account.id,
        status="completed",
        found_count=10,
        target_results=10,
        updated_at=datetime.now(timezone.utc),
    )
    db.add_all([account, device_a, device_b, job])
    db.commit()
    return job


class _FakeClient:
    def __init__(self, statuses: dict[str, list[int]], calls: list[str], *args, **kwargs):
        self.statuses = statuses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, _endpoint, json):
        token = json["message"]["token"]
        self.calls.append(token)
        status = self.statuses[token].pop(0)
        text = "UNREGISTERED" if status == 404 else ""
        return SimpleNamespace(status_code=status, text=text)


def _enable_fake_firebase(monkeypatch) -> None:
    monkeypatch.setattr(notifications.settings, "notifications_enabled", True)
    credentials = SimpleNamespace(valid=True, token="access-token")
    monkeypatch.setattr(notifications, "_firebase_credentials", lambda: (credentials, "project-1"))


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
    db = _memory_session()
    try:
        job = _seed_notification_job(db)
        monkeypatch.setattr(notifications.settings, "notifications_enabled", True)
        monkeypatch.setattr(notifications, "_firebase_credentials", lambda: None)

        assert notifications.send_job_pushes(db, job) is False
        rows = list(db.scalars(select(NotificationDelivery)).all())
        assert len(rows) == 2
        assert {row.state for row in rows} == {"pending"}
    finally:
        db.close()


def test_retry_only_targets_devices_that_did_not_receive_push(monkeypatch) -> None:
    db = _memory_session()
    try:
        job = _seed_notification_job(db)
        _enable_fake_firebase(monkeypatch)

        first_calls: list[str] = []
        first_statuses = {"token-a": [200], "token-b": [503]}
        monkeypatch.setattr(
            notifications.httpx,
            "Client",
            lambda *args, **kwargs: _FakeClient(first_statuses, first_calls, *args, **kwargs),
        )

        assert notifications.send_job_pushes(db, job) is False
        states = {
            row.device_id: row.state
            for row in db.scalars(select(NotificationDelivery)).all()
        }
        assert states == {"device-a": "sent", "device-b": "pending"}
        assert first_calls == ["token-a", "token-b"]

        second_calls: list[str] = []
        second_statuses = {"token-b": [200]}
        monkeypatch.setattr(
            notifications.httpx,
            "Client",
            lambda *args, **kwargs: _FakeClient(second_statuses, second_calls, *args, **kwargs),
        )

        assert notifications.send_job_pushes(db, job) is True
        assert second_calls == ["token-b"]
        states = {
            row.device_id: row.state
            for row in db.scalars(select(NotificationDelivery)).all()
        }
        assert states == {"device-a": "sent", "device-b": "sent"}
    finally:
        db.close()


def test_new_completion_cycle_notifies_devices_again(monkeypatch) -> None:
    db = _memory_session()
    try:
        job = _seed_notification_job(db)
        _enable_fake_firebase(monkeypatch)

        initial_calls: list[str] = []
        initial_statuses = {"token-a": [200], "token-b": [200]}
        monkeypatch.setattr(
            notifications.httpx,
            "Client",
            lambda *args, **kwargs: _FakeClient(initial_statuses, initial_calls, *args, **kwargs),
        )
        assert notifications.send_job_pushes(db, job) is True
        assert initial_calls == ["token-a", "token-b"]

        job.updated_at = datetime.now(timezone.utc) + timedelta(seconds=2)
        db.commit()

        next_calls: list[str] = []
        next_statuses = {"token-a": [200], "token-b": [200]}
        monkeypatch.setattr(
            notifications.httpx,
            "Client",
            lambda *args, **kwargs: _FakeClient(next_statuses, next_calls, *args, **kwargs),
        )
        assert notifications.send_job_pushes(db, job) is True
        assert next_calls == ["token-a", "token-b"]
    finally:
        db.close()
