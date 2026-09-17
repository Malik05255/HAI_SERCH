from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Job


ACTIVE_STATES = ("queued", "running", "stopped")
QUEUE_LOCK_KEY = 847251901


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _head_is_runnable(head: Job, now: datetime) -> bool:
    if head.status != "queued" or head.stop_requested:
        return False
    if head.next_run_at is not None and head.next_run_at > now:
        return False
    return True


def _first_runnable_account_head(jobs: list[Job], now: datetime) -> Job | None:
    """Return the oldest runnable head while preserving FIFO per account.

    Input must already be globally ordered by creation time. Only the first
    unfinished job of each account is eligible. A stopped/backoff head blocks
    later jobs in the same account but must never block a different account.
    """
    seen_accounts: set[str] = set()
    for job in jobs:
        account_id = job.account_id
        if not account_id or account_id in seen_accounts:
            continue
        seen_accounts.add(account_id)
        if _head_is_runnable(job, now):
            return job
    return None


def claim_next_job(db: Session) -> Job | None:
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK_KEY}).scalar()
    if not locked:
        db.rollback()
        return None

    now = utcnow()
    # One worker executes one search at a time globally, but FIFO blocking is
    # scoped to an account. This keeps linked devices consistent without one
    # user's paused job freezing every other account on the server.
    active_jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.account_id.is_not(None),
                Job.status.in_(ACTIVE_STATES),
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
        ).all()
    )
    candidate = _first_runnable_account_head(active_jobs, now)
    if candidate is None:
        db.commit()
        return None

    # Lock only the selected row. API actions may stop/cancel jobs concurrently,
    # so revalidate after the lock instead of trusting the earlier snapshot.
    head = db.execute(
        select(Job)
        .where(Job.id == candidate.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if head is None or not _head_is_runnable(head, now):
        db.commit()
        return None

    head.status = "running"
    head.heartbeat_at = now
    head.attempts += 1
    db.commit()
    db.refresh(head)
    return head


def requeue(db: Session, job: Job) -> None:
    delay_minutes = min(60, max(2, 2 ** min(job.attempts // 3, 5)))
    job.status = "queued"
    job.next_run_at = utcnow() + timedelta(minutes=delay_minutes)
    job.heartbeat_at = None
    db.commit()
