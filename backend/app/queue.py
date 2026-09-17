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


def claim_next_job(db: Session) -> Job | None:
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK_KEY}).scalar()
    if not locked:
        db.rollback()
        return None

    now = utcnow()
    # Strict FIFO: inspect the oldest unfinished job first. Do not skip a
    # stopped job or a retrying job whose backoff has not expired; everything
    # behind it remains queued until this head job resumes, completes or is
    # cancelled/deleted.
    head = db.execute(
        select(Job)
        .where(
            Job.account_id.is_not(None),
            Job.status.in_(ACTIVE_STATES),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
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
