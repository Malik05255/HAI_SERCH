import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import settings
from .database import Base, SessionLocal, engine
from .maintenance import cleanup_orphan_uploads, recover_interrupted_jobs
from .models import Job
from .notifications import send_job_pushes
from .worker import process_one


CLEANUP_INTERVAL_SECONDS = 3600
NOTIFICATION_INTERVAL_SECONDS = 15
NOTIFIABLE_STATES = ("completed", "partial", "failed", "needs_context")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        with SessionLocal() as db:
            recover_interrupted_jobs(db)
    except Exception:
        # The worker can still start; the next deployment/run can recover again.
        pass

    last_cleanup = 0.0
    last_notifications = 0.0
    started_at = datetime.now(timezone.utc)
    notified: set[str] = set()

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

        if settings.notifications_enabled and now - last_notifications >= NOTIFICATION_INTERVAL_SECONDS:
            try:
                with SessionLocal() as db:
                    jobs = list(
                        db.scalars(
                            select(Job)
                            .where(
                                Job.status.in_(NOTIFIABLE_STATES),
                                Job.updated_at >= started_at,
                            )
                            .order_by(Job.updated_at.asc())
                        ).all()
                    )
                    for job in jobs:
                        if job.id in notified:
                            continue
                        if send_job_pushes(db, job):
                            notified.add(job.id)
            except Exception:
                # Push delivery is optional and must never stop research.
                pass
            last_notifications = now

        worked = process_one()
        if not worked:
            time.sleep(settings.search_idle_sleep_seconds)


if __name__ == "__main__":
    main()
