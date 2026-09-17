from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .auth import Principal, create_pair_code, pair_device, register_device, require_principal
from .config import settings
from .database import Base, engine, get_db
from .media import IMAGE_EXTS, VIDEO_EXTS, account_upload_root, delete_uploaded_media, resolve_upload_id
from .models import Device, Job, Result
from .queue import ACTIVE_STATES
from .schemas import JobCreate, JobOut, ResultOut


CREATE_LOCK_KEY = 847251902
FINAL_STATES = ("completed", "partial", "failed", "needs_context", "cancelled")
app = FastAPI(title=settings.app_name, version="0.5.0")


class DeviceCreate(BaseModel):
    name: str = Field(default="Device", min_length=1, max_length=120)


class PairDevice(BaseModel):
    code: str = Field(min_length=6, max_length=20)
    name: str = Field(default="Device", min_length=1, max_length=120)


@app.on_event("startup")
def startup() -> None:
    Path(settings.data_dir, "uploads").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS account_id VARCHAR(36) NULL")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_jobs_account_id ON jobs (account_id)")


def _queue_positions(db: Session, account_id: str) -> dict[str, int]:
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.account_id == account_id, Job.status.in_(ACTIVE_STATES))
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
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _owned_job(db: Session, job_id: str, principal: Principal) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.account_id == principal.account_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": settings.app_name}


@app.post("/v1/auth/register")
def register(payload: DeviceCreate, db: Session = Depends(get_db)) -> dict:
    return register_device(db, payload.name)


@app.post("/v1/auth/pair")
def pair(payload: PairDevice, db: Session = Depends(get_db)) -> dict:
    return pair_device(db, payload.code, payload.name)


@app.post("/v1/auth/pair-code")
def new_pair_code(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict:
    return create_pair_code(db, principal)


@app.get("/v1/auth/devices")
def devices(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = list(db.scalars(select(Device).where(Device.account_id == principal.account_id).order_by(Device.created_at.asc())).all())
    return [{"id": d.id, "name": d.name, "current": d.id == principal.device_id, "created_at": d.created_at} for d in rows]


@app.delete("/v1/auth/devices/{device_id}")
def revoke_device(
    device_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict:
    device = db.scalar(select(Device).where(Device.id == device_id, Device.account_id == principal.account_id))
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if device.id == principal.device_id:
        raise HTTPException(status_code=409, detail="cannot revoke current device")
    db.delete(device)
    db.commit()
    return {"ok": True}


@app.post("/v1/uploads")
async def upload(file: UploadFile, principal: Principal = Depends(require_principal)) -> dict:
    max_bytes = settings.video_max_upload_mb * 1024 * 1024
    suffix = Path(file.filename or "upload.bin").suffix.casefold()[:12]
    key = f"{uuid4()}{suffix}"
    destination = account_upload_root(principal.account_id) / key
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


@app.post("/v1/jobs", response_model=JobOut)
def create_job(
    payload: JobCreate,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict:
    input_url = None
    if payload.upload_id:
        path = resolve_upload_id(payload.upload_id, principal.account_id)
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
            Job.account_id == principal.account_id,
            Job.status.in_(ACTIVE_STATES),
        )
    ) or 0
    if active_count >= settings.search_max_active_jobs:
        if input_url:
            delete_uploaded_media(input_url)
        db.rollback()
        raise HTTPException(status_code=429, detail="search queue is full (5/5)")

    job = Job(
        account_id=principal.account_id,
        query=payload.query.strip(),
        input_type=payload.input_type,
        input_url=input_url,
        target_results=min(payload.target_results, settings.search_max_results),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db, principal.account_id))


@app.get("/v1/jobs", response_model=list[JobOut])
def list_jobs(
    view: str = "all",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> list[dict]:
    positions = _queue_positions(db, principal.account_id)
    stmt = select(Job).where(Job.account_id == principal.account_id)
    if view == "queue":
        stmt = stmt.where(Job.status.in_(ACTIVE_STATES)).order_by(Job.created_at.asc())
    elif view == "history":
        stmt = stmt.where(Job.status.in_(FINAL_STATES)).order_by(Job.updated_at.desc())
    elif view == "all":
        stmt = stmt.order_by(Job.created_at.desc())
    else:
        raise HTTPException(status_code=422, detail="invalid view")
    jobs = list(db.scalars(stmt.limit(100)).all())
    return [_job_out(job, positions) for job in jobs]


@app.get("/v1/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> dict:
    job = _owned_job(db, job_id, principal)
    return _job_out(job, _queue_positions(db, principal.account_id))


@app.get("/v1/jobs/{job_id}/results", response_model=list[ResultOut])
def get_results(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> list[Result]:
    _owned_job(db, job_id, principal)
    return list(db.scalars(select(Result).where(Result.job_id == job_id).order_by(Result.rank.asc())).all())


@app.post("/v1/jobs/{job_id}/stop", response_model=JobOut)
def stop_job(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> dict:
    job = _owned_job(db, job_id, principal)
    if job.status not in FINAL_STATES:
        job.stop_requested = True
        job.status = "stopped"
        db.commit()
        db.refresh(job)
    return _job_out(job, _queue_positions(db, principal.account_id))


@app.post("/v1/jobs/{job_id}/resume", response_model=JobOut)
def resume_job(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> dict:
    job = _owned_job(db, job_id, principal)
    if job.status == "stopped":
        job.stop_requested = False
        job.status = "queued"
        db.commit()
        db.refresh(job)
    return _job_out(job, _queue_positions(db, principal.account_id))


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> dict:
    job = _owned_job(db, job_id, principal)
    job.stop_requested = True
    job.status = "cancelled"
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None
    db.commit()
    db.refresh(job)
    return _job_out(job, _queue_positions(db, principal.account_id))


@app.delete("/v1/jobs/{job_id}")
def delete_job(job_id: str, principal: Principal = Depends(require_principal), db: Session = Depends(get_db)) -> dict:
    job = _owned_job(db, job_id, principal)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="cancel running job before deleting")
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None
    db.delete(job)
    db.commit()
    return {"ok": True}
