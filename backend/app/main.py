from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .media import delete_uploaded_media
from .models import Job, Result
from .schemas import JobCreate, JobOut, ResultOut


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    Path(settings.data_dir, "uploads").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if settings.app_env == "development" and not settings.api_token:
        return
    if not settings.api_token or x_api_key != settings.api_token:
        raise HTTPException(status_code=401, detail="invalid api key")


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
    return {"input_url": str(destination), "input_type": input_type, "size": written, "temporary": True}


@app.post("/v1/jobs", response_model=JobOut, dependencies=[Depends(require_api_key)])
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> Job:
    job = Job(
        query=payload.query.strip(),
        input_type=payload.input_type,
        input_url=payload.input_url,
        target_results=min(payload.target_results, settings.search_max_results),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.get("/v1/jobs", response_model=list[JobOut], dependencies=[Depends(require_api_key)])
def list_jobs(db: Session = Depends(get_db)) -> list[Job]:
    return list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100)).all())


@app.get("/v1/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_api_key)])
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/v1/jobs/{job_id}/results", response_model=list[ResultOut], dependencies=[Depends(require_api_key)])
def get_results(job_id: str, db: Session = Depends(get_db)) -> list[Result]:
    return list(db.scalars(select(Result).where(Result.job_id == job_id).order_by(Result.rank.asc())).all())


@app.post("/v1/jobs/{job_id}/stop", response_model=JobOut, dependencies=[Depends(require_api_key)])
def stop_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    was_running = job.status == "running"
    job.stop_requested = True
    job.status = "stopped"
    if not was_running and job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None
    db.commit()
    db.refresh(job)
    return job


@app.post("/v1/jobs/{job_id}/resume", response_model=JobOut, dependencies=[Depends(require_api_key)])
def resume_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job.stop_requested = False
    job.status = "queued"
    db.commit()
    db.refresh(job)
    return job
