from datetime import timedelta

from app.models import Job
from app.queue import _head_is_runnable, utcnow


def test_stopped_head_blocks_fifo_queue() -> None:
    now = utcnow()
    head = Job(status="stopped", stop_requested=True, next_run_at=now - timedelta(minutes=1))

    assert _head_is_runnable(head, now) is False


def test_retry_backoff_head_blocks_fifo_queue() -> None:
    now = utcnow()
    head = Job(status="queued", stop_requested=False, next_run_at=now + timedelta(minutes=5))

    assert _head_is_runnable(head, now) is False


def test_oldest_ready_queued_job_can_run() -> None:
    now = utcnow()
    head = Job(status="queued", stop_requested=False, next_run_at=now - timedelta(seconds=1))

    assert _head_is_runnable(head, now) is True
