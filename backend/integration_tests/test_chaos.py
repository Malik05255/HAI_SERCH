from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import func, select

import app.worker as worker
from app.auth import principal_for_token
from app.database import SessionLocal
from app.main import create_job
from app.maintenance import recover_interrupted_jobs
from app.models import Job
from app.schemas import JobCreate


def test_queue_capacity_is_atomic_under_concurrent_submissions(linked_devices) -> None:
    token = linked_devices["android"]["token"]
    with SessionLocal() as db:
        principal = principal_for_token(db, token)
        assert principal is not None

    gate = Barrier(8)

    def submit(index: int) -> int:
        gate.wait(timeout=10)
        with SessionLocal() as db:
            try:
                create_job(
                    JobCreate(
                        query=f"concurrent search {index}",
                        input_type="text",
                        target_results=1,
                    ),
                    principal=principal,
                    db=db,
                )
                return 200
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(submit, range(8)))

    assert statuses.count(200) == 5
    assert statuses.count(429) == 3

    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Job).where(
                Job.account_id == principal.account_id,
                Job.status.in_(("queued", "running", "stopped")),
            )
        )
        assert active == 5


def test_worker_restart_recovers_running_job(linked_devices) -> None:
    token = linked_devices["android"]["token"]
    with SessionLocal() as db:
        principal = principal_for_token(db, token)
        assert principal is not None
        job = Job(
            account_id=principal.account_id,
            query="recover me",
            input_type="text",
            status="running",
            heartbeat_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        job_id = job.id

    with SessionLocal() as db:
        assert recover_interrupted_jobs(db) == 1

    with SessionLocal() as db:
        recovered = db.get(Job, job_id)
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.stop_requested is False
        assert recovered.heartbeat_at is None


def test_search_outage_requeues_instead_of_crashing(client, linked_devices, monkeypatch) -> None:
    created = client.post(
        "/v1/jobs",
        headers=linked_devices["android_headers"],
        json={"query": "temporary outage", "input_type": "text", "target_results": 1},
    )
    assert created.status_code == 200
    job_id = created.json()["id"]

    monkeypatch.setattr(worker, "media_features", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "plan_queries", lambda _query: ["temporary outage"])

    async def broken_research(*_args, **_kwargs):
        raise RuntimeError("searx unavailable")

    monkeypatch.setattr(worker, "run_research", broken_research)

    assert worker.process_one() is True

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "queued"
        assert job.attempts == 1
        assert "RuntimeError" in (job.last_error or "")
        assert job.next_run_at is not None
