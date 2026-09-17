from datetime import timedelta

from app.models import Job
from app.queue import _first_runnable_account_head, _head_is_runnable, utcnow


def _job(account: str, status: str, *, stop: bool = False, delay_minutes: int = -1) -> Job:
    now = utcnow()
    return Job(
        account_id=account,
        status=status,
        stop_requested=stop,
        next_run_at=now + timedelta(minutes=delay_minutes),
    )


def test_stopped_head_blocks_fifo_queue_for_same_account() -> None:
    now = utcnow()
    head = Job(status="stopped", stop_requested=True, next_run_at=now - timedelta(minutes=1))

    assert _head_is_runnable(head, now) is False


def test_retry_backoff_head_blocks_fifo_queue_for_same_account() -> None:
    now = utcnow()
    head = Job(status="queued", stop_requested=False, next_run_at=now + timedelta(minutes=5))

    assert _head_is_runnable(head, now) is False


def test_oldest_ready_queued_job_can_run() -> None:
    now = utcnow()
    head = Job(status="queued", stop_requested=False, next_run_at=now - timedelta(seconds=1))

    assert _head_is_runnable(head, now) is True


def test_stopped_account_does_not_block_another_account() -> None:
    now = utcnow()
    jobs = [
        _job("account-a", "stopped", stop=True),
        _job("account-a", "queued"),
        _job("account-b", "queued"),
    ]

    selected = _first_runnable_account_head(jobs, now)

    assert selected is jobs[2]


def test_backoff_account_does_not_skip_to_its_second_job() -> None:
    now = utcnow()
    jobs = [
        _job("account-a", "queued", delay_minutes=5),
        _job("account-a", "queued"),
        _job("account-b", "queued"),
    ]

    selected = _first_runnable_account_head(jobs, now)

    assert selected is jobs[2]


def test_ready_oldest_account_head_keeps_global_worker_priority() -> None:
    now = utcnow()
    jobs = [
        _job("account-a", "queued"),
        _job("account-b", "queued"),
    ]

    selected = _first_runnable_account_head(jobs, now)

    assert selected is jobs[0]
