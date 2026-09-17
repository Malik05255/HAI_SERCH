from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job(db: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(
            Job.status == "queued",
            Job.stop_requested.is_(False),
            Job.next_run_at <= utcnow(),
        )
        .order_by(Job.next_run_at.asc(), Job.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        db.commit()
        return None
    job.status = "running"
    job.heartbeat_at = utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def requeue(db: Session, job: Job) -> None:
    delay_minutes = min(60, max(2, 2 ** min(job.attempts // 3, 5)))
    job.status = "queued"
    job.next_run_at = utcnow() + timedelta(minutes=delay_minutes)
    job.heartbeat_at = None
    db.commit()
