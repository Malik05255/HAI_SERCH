import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import settings
from .database import SessionLocal, ensure_schema
from .maintenance import cleanup_orphan_uploads, recover_interrupted_jobs
from .models import Job
from .notifications import send_job_pushes
from .worker import process_one


CLEANUP_INTERVAL_SECONDS = 3600
NOTIFICATION_RETRY_INTERVAL_SECONDS = 30


def _retry_pending_notifications() -> int:
    if not settings.notifications_enabled:
        return 0

    delivered = 0
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(Job)
                .where(
                    Job.notification_pending.is_(True),
                    Job.status.in_(("completed", "partial")),
                )
                .order_by(Job.updated_at.asc())
                .limit(20)
            ).all()
        )
        for job in jobs:
            try:
                handled = send_job_pushes(db, job)
            except Exception:
                handled = False
            if not handled:
                continue
            job.notification_pending = False
            job.notification_sent_at = datetime.now(timezone.utc)
            delivered += 1
        if delivered:
            db.commit()
    return delivered


def main() -> None:
    ensure_schema()
    try:
        with SessionLocal() as db:
            recover_interrupted_jobs(db)
    except Exception:
        # The worker can still start; the next deployment/run can recover again.
        pass

    last_cleanup = 0.0
    last_notification_retry = 0.0

    while True:
        now = time.monotonic()
        if now - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
            try:
                with SessionLocal() as db:
                    cleanup_orphan_uploads(db)
            except Exception:
                # Cleanup must never stop research execution.
                pass
            last_cleanup = now

        if now - last_notification_retry >= NOTIFICATION_RETRY_INTERVAL_SECONDS:
            try:
                _retry_pending_notifications()
            except Exception:
                # Notification retry is optional and must never stop research.
                pass
            last_notification_retry = now

        worked = process_one()
        if not worked:
            time.sleep(settings.search_idle_sleep_seconds)


if __name__ == "__main__":
    main()
