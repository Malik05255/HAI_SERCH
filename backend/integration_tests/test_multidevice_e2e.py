from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import select

import app.worker as worker
from app.database import SessionLocal
from app.models import Job
from app.research import Candidate


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_android_to_windows_full_text_research_cycle(client, linked_devices, monkeypatch) -> None:
    android_headers = linked_devices["android_headers"]
    windows_headers = linked_devices["windows_headers"]

    created = client.post(
        "/v1/jobs",
        headers=android_headers,
        json={
            "query": "فيلم البطل يخرج من القرية إلى المدينة",
            "input_type": "text",
            "target_results": 2,
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]

    windows_queue = client.get("/v1/jobs?view=queue", headers=windows_headers)
    assert windows_queue.status_code == 200
    assert [job["id"] for job in windows_queue.json()] == [job_id]

    monkeypatch.setattr(worker, "media_features", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "plan_queries", lambda _query: ["hero village city"])

    async def fake_research(*_args, **_kwargs):
        return [
            Candidate(
                title="Candidate One (2020)",
                url="https://source-a.example/item",
                image_url=None,
                snippet="",
                summary="The hero leaves the village for the city.",
                score=94.0,
                page_verified=True,
            ),
            Candidate(
                title="Candidate Two (2019)",
                url="https://source-b.example/item",
                image_url=None,
                snippet="",
                summary="A second independently verified candidate.",
                score=88.0,
                page_verified=True,
            ),
        ]

    monkeypatch.setattr(worker, "run_research", fake_research)
    assert worker.process_one() is True

    android_job = client.get(f"/v1/jobs/{job_id}", headers=android_headers)
    windows_job = client.get(f"/v1/jobs/{job_id}", headers=windows_headers)
    assert android_job.json()["status"] == "completed"
    assert windows_job.json()["status"] == "completed"
    assert android_job.json()["found_count"] == 2

    results = client.get(f"/v1/jobs/{job_id}/results", headers=windows_headers)
    assert results.status_code == 200
    assert [item["rank"] for item in results.json()] == [1, 2]

    with client.websocket_connect("/v1/ws", headers=windows_headers) as websocket:
        event = websocket.receive_json()
        assert event["type"] == "jobs.changed"
        assert any(item["id"] == job_id and item["status"] == "completed" for item in event["jobs"])

    clue = client.post(
        f"/v1/jobs/{job_id}/clues",
        headers=windows_headers,
        json={"text": "البطل يعمل سائقًا"},
    )
    assert clue.status_code == 200
    assert clue.json()["status"] == "queued"

    seen_from_android = client.get(f"/v1/jobs/{job_id}", headers=android_headers)
    assert seen_from_android.json()["status"] == "queued"

    revoke = client.delete(
        f"/v1/auth/devices/{linked_devices['windows']['device_id']}",
        headers=android_headers,
    )
    assert revoke.status_code == 200
    assert client.get("/v1/jobs", headers=windows_headers).status_code == 401


def test_media_uploaded_on_one_device_is_downloadable_on_other_then_purged(
    client,
    linked_devices,
) -> None:
    android_headers = linked_devices["android_headers"]
    windows_headers = linked_devices["windows_headers"]
    payload = _png_bytes()

    upload = client.post(
        "/v1/uploads",
        headers=android_headers,
        files={"file": ("frame.png", payload, "image/png")},
    )
    assert upload.status_code == 200

    created = client.post(
        "/v1/jobs",
        headers=android_headers,
        json={
            "query": "تعرف على هذه الصورة",
            "input_type": "image",
            "upload_id": upload.json()["upload_id"],
            "target_results": 1,
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]

    downloaded = client.get(f"/v1/jobs/{job_id}/media", headers=windows_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == payload

    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        worker.finish_job(db, job, "completed", 1.0)

    assert client.get(f"/v1/jobs/{job_id}/media", headers=windows_headers).status_code == 404
