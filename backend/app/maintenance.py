import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Job


def _resolved(value: str | Path) -> str:
    return str(Path(value).resolve(strict=False))


def prune_orphan_files(root: Path, referenced_paths: set[str], cutoff_epoch: float) -> int:
    """Delete only expired upload files that are not referenced by any job."""
    root.mkdir(parents=True, exist_ok=True)
    referenced = {_resolved(value) for value in referenced_paths}
    removed = 0

    for account_dir in root.iterdir():
        if not account_dir.is_dir():
            continue
        analysis_dir = account_dir / ".analysis"
        for path in account_dir.iterdir():
            if not path.is_file():
                continue
            try:
                if _resolved(path) in referenced or path.stat().st_mtime > cutoff_epoch:
                    continue
            except OSError:
                continue

            try:
                path.unlink(missing_ok=True)
                removed += 1
                (analysis_dir / f"{path.name}.json").unlink(missing_ok=True)
            except OSError:
                continue

        try:
            if analysis_dir.is_dir() and not any(analysis_dir.iterdir()):
                analysis_dir.rmdir()
            if account_dir.is_dir() and not any(account_dir.iterdir()):
                account_dir.rmdir()
        except OSError:
            pass

    return removed


def cleanup_orphan_uploads(db: Session, *, now_epoch: float | None = None) -> int:
    ttl_hours = settings.temp_file_ttl_hours
    if ttl_hours <= 0:
        return 0

    referenced = {
        _resolved(value)
        for value in db.scalars(select(Job.input_url).where(Job.input_url.is_not(None))).all()
        if value
    }
    cutoff = (now_epoch if now_epoch is not None else time.time()) - ttl_hours * 3600
    return prune_orphan_files(Path(settings.data_dir, "uploads"), referenced, cutoff)


def recover_interrupted_jobs(db: Session) -> int:
    """Return jobs left as running by a previous worker process back to the queue."""
    jobs = list(db.scalars(select(Job).where(Job.status == "running")).all())
    if not jobs:
        return 0

    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "queued"
        job.stop_requested = False
        job.next_run_at = now
        job.heartbeat_at = None
    db.commit()
    return len(jobs)
