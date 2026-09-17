import time

from .config import settings
from .database import SessionLocal, ensure_schema
from .maintenance import cleanup_orphan_uploads, recover_interrupted_jobs
from .worker import process_one


CLEANUP_INTERVAL_SECONDS = 3600


def main() -> None:
    ensure_schema()
    try:
        with SessionLocal() as db:
            recover_interrupted_jobs(db)
    except Exception:
        # The worker can still start; the next deployment/run can recover again.
        pass

    last_cleanup = 0.0

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

        worked = process_one()
        if not worked:
            time.sleep(settings.search_idle_sleep_seconds)


if __name__ == "__main__":
    main()
