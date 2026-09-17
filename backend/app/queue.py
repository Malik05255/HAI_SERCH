from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Job


ACTIVE_STATES = ("queued", "running", "stopped")
QUEUE_LOCK_KEY = 847251901


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job(db: Session) -> Job | None:
    # One global research slot by design. The transaction advisory lock makes
    # this safe even if more than one worker process is accidentally started.
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK_KEY}).scalar()
    if not locked:
        db.rollback()
        return None

    head = db.execute(
        select(Job)
        .where(Job.status.in_(ACTIVE_STATES))
        .order_by(Job.created_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()

    if head is None:
        db.commit()
        return None

    # Strict FIFO: a paused/running/temporarily backed-off head blocks later jobs.
    if head.status != "queued" or head.stop_requested or head.next_run_at > utcnow():
        db.commit()
        return None

    head.status = "running"
    head.heartbeat_at = utcnow()
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
