from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .media import IMAGE_EXTS, VIDEO_EXTS, delete_uploaded_media, resolve_upload_id
from .models import Job, Result
from .queue import ACTIVE_STATES
from .schemas import JobCreate, JobOut, ResultOut


CREATE_LOCK_KEY = 847251902
FINAL_STATES = ("completed", "partial", "failed", "needs_context", "cancelled")
app = FastAPI(title=settings.app_name, version="0.4.0")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@app.on_event("startup")
def startup() -> None:
    Path(settings.data_dir, "uploads").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    # Lightweight forward migration for deployments created before archive support.
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_jobs_archived ON jobs (archived)")


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if settings.app_env == "development" and not settings.api_token:
        return
    if not settings.api_token or x_api_key != settings.api_token:
        raise HTTPException(status_code=401, detail="invalid api key")


def _queue_positions(db: Session) -> dict[str, int]:
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.status.in_(ACTIVE_STATES), Job.archived.is_(False))
            .order_by(Job.created_at.asc(), Job.id.asc())
        ).all()
    )
    return {job.id: index for index, job in enumerate(jobs, start=1)}


def _job_out(job: Job, positions: dict[str, int]) -> dict:
    return {
        "id": job.id,
        "query": job.query,
        "input_type": job.input_type,
        "target_results": job.target_results,
        "status": job.status,
        "progress": job.progress,
        "found_count": job.found_count,
        "attempts": job.attempts,
        "queue_position": positions.get(job.id),
        "archived": bool(job.archived),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": settings.app_name}


@app.post("/v1/uploads", dependencies=[Depends(require_api_key)])
async def upload(file: UploadFile) -> dict:
    max_bytes = settings.video_max_upload_mb * 1024 * 1024
    suffix = Path(file.filename or "upload.bin").suffix.casefold()[:12]
    key = f"{uuid4()}{suffix}"
    destination = Path(settings.data_dir, "uploads", key)
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="file too large")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    content_type = file.content_type or ""
    if content_type.startswith("video/") or suffix in VIDEO_EXTS:
        input_type = "video"
    elif content_type.startswith("image/") or suffix in IMAGE_EXTS:
        input_type = "image"
    else:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="unsupported media type")
    return {"upload_id": key, "input_type": input_type, "size": written, "temporary": True}


@app.post("/v1/jobs", response_model=JobOut, dependencies=[Depends(require_api_key)])
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> dict:
    input_url = None
    if payload.upload_id:
        path = resolve_upload_id(payload.upload_id)
        if path is None:
            raise HTTPException(status_code=404, detail="temporary upload not found")
        suffix = path.suffix.casefold()
        actual_type = "video" if suffix in VIDEO_EXTS else "image" if suffix in IMAGE_EXTS else None
        if actual_type is None or actual_type != payload.input_type:
            raise HTTPException(status_code=422, detail="upload type mismatch")
        input_url = str(path)

    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CREATE_LOCK_KEY})
    active_count = db.scalar(
        select(func.count()).select_from(Job).where(
            Job.status.in_(ACTIVE_STATES), Job.archived.is_(False)
        )
    ) or 0
    if active_count >= settings.search_max_active_jobs:
        if input_url:
            delete_uploaded_media(input_url)
        db.rollback()
        raise HTTPException(status_code=429, detail="search queue is full (5/5)")

    job = Job(
        query=payload.query.strip(),
        input_type=payload.input_type,
        input_url=input_url,
        target_results=min(payload.target_results, settings.search_max_results),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.get("/v1/jobs", response_model=list[JobOut], dependencies=[Depends(require_api_key)])
def list_jobs(view: str = "all", db: Session = Depends(get_db)) -> list[dict]:
    positions = _queue_positions(db)
    stmt = select(Job)
    if view == "queue":
        stmt = stmt.where(Job.archived.is_(False), Job.status.in_(ACTIVE_STATES)).order_by(Job.created_at.asc())
    elif view == "archive":
        stmt = stmt.where(Job.archived.is_(True)).order_by(Job.archived_at.desc(), Job.updated_at.desc())
    elif view == "history":
        stmt = stmt.where(Job.archived.is_(False), Job.status.in_(FINAL_STATES)).order_by(Job.updated_at.desc())
    elif view == "all":
        stmt = stmt.where(Job.archived.is_(False)).order_by(Job.created_at.desc())
    else:
        raise HTTPException(status_code=422, detail="invalid view")
    jobs = list(db.scalars(stmt.limit(100)).all())
    return [_job_out(job, positions) for job in jobs]


@app.get("/v1/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_api_key)])
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_out(job, _queue_positions(db))


@app.get("/v1/jobs/{job_id}/results", response_model=list[ResultOut], dependencies=[Depends(require_api_key)])
def get_results(job_id: str, db: Session = Depends(get_db)) -> list[Result]:
    return list(db.scalars(select(Result).where(Result.job_id == job_id).order_by(Result.rank.asc())).all())


@app.post("/v1/jobs/{job_id}/stop", response_model=JobOut, dependencies=[Depends(require_api_key)])
def stop_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.archived and job.status not in FINAL_STATES:
        job.stop_requested = True
        job.status = "stopped"
        db.commit()
        db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.post("/v1/jobs/{job_id}/resume", response_model=JobOut, dependencies=[Depends(require_api_key)])
def resume_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.archived and job.status == "stopped":
        job.stop_requested = False
        job.status = "queued"
        db.commit()
        db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobOut, dependencies=[Depends(require_api_key)])
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job.stop_requested = True
    job.status = "cancelled"
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.post("/v1/jobs/{job_id}/archive", response_model=JobOut, dependencies=[Depends(require_api_key)])
def archive_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in ACTIVE_STATES:
        job.stop_requested = True
        job.status = "cancelled"
        if job.input_url:
            delete_uploaded_media(job.input_url)
            job.input_url = None
    job.archived = True
    job.archived_at = utcnow()
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.post("/v1/jobs/{job_id}/restore", response_model=JobOut, dependencies=[Depends(require_api_key)])
def restore_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job.archived = False
    job.archived_at = None
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db))


@app.delete("/v1/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None
    db.delete(job)
    db.commit()
    return {"ok": True}
