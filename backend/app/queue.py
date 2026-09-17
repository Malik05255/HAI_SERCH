from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Job


ACTIVE_STATES = ("queued", "running", "stopped")
QUEUE_LOCK_KEY = 847251901


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job(db: Session) -> Job | None:
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": QUEUE_LOCK_KEY}).scalar()
    if not locked:
        db.rollback()
        return None

    now = utcnow()
    head = db.execute(
        select(Job)
        .where(
            Job.account_id.is_not(None),
            Job.status == "queued",
            Job.stop_requested.is_(False),
            Job.next_run_at <= now,
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()

    if head is None:
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
