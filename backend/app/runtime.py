import time

from .config import settings
from .database import Base, SessionLocal, engine
from .maintenance import cleanup_orphan_uploads
from .worker import process_one


CLEANUP_INTERVAL_SECONDS = 3600


def main() -> None:
    Base.metadata.create_all(bind=engine)
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
