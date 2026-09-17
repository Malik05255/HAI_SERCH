import asyncio
import hmac
import json

import httpx
from fastapi import Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, principal_for_token, require_principal
from .config import settings
from .database import SessionLocal, get_db
from .egress import EgressRouter
from .main import app
from .models import Device, Job, Result


RESULT_IMAGE_MAX_BYTES = 6 * 1024 * 1024
REALTIME_INTERVAL_SECONDS = 2.0


class PushTokenUpdate(BaseModel):
    token: str | None = Field(default=None, max_length=4096)


@app.put("/v1/auth/push-token")
def update_push_token(
    payload: PushTokenUpdate,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, principal.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    token = (payload.token or "").strip()
    device.push_token = token or None
    db.commit()
    return {"ok": True, "enabled": bool(device.push_token)}


def _realtime_snapshot(principal: Principal) -> list[dict] | None:
    with SessionLocal() as db:
        device = db.get(Device, principal.device_id)
        if device is None or device.account_id != principal.account_id:
            return None
        jobs = list(
            db.scalars(
                select(Job)
                .where(Job.account_id == principal.account_id)
                .order_by(Job.updated_at.desc(), Job.id.asc())
                .limit(100)
            ).all()
        )
        return [
            {
                "id": job.id,
                "status": job.status,
                "progress": round(float(job.progress or 0), 4),
                "found_count": job.found_count,
                "target_results": job.target_results,
                "attempts": job.attempts,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            }
            for job in jobs
        ]


@app.websocket("/v1/ws")
async def realtime_jobs(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        await websocket.close(code=4401)
        return

    with SessionLocal() as db:
        principal = principal_for_token(db, authorization[7:])
    if principal is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    previous = ""
    try:
        while True:
            snapshot = await asyncio.to_thread(_realtime_snapshot, principal)
            if snapshot is None:
                await websocket.close(code=4401)
                return

            fingerprint = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
            if fingerprint != previous:
                await websocket.send_json({"type": "jobs.changed", "jobs": snapshot})
                previous = fingerprint

            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=REALTIME_INTERVAL_SECONDS,
                )
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


async def _proxy_result_image(result: Result) -> Response:
    image_url = (result.image_url or "").strip()
    if not image_url:
        raise HTTPException(status_code=404, detail="result image not available")

    timeout = httpx.Timeout(settings.search_http_timeout_seconds)
    headers = {
        "User-Agent": "DeepSearch/0.11 (+result image proxy)",
        "Accept": "image/*",
    }
    try:
        async with EgressRouter(timeout=timeout, headers=headers) as egress:
            upstream, content = await egress.get_bytes(
                image_url,
                max_bytes=RESULT_IMAGE_MAX_BYTES,
            )
    except ValueError as error:
        if str(error) == "response_too_large":
            raise HTTPException(status_code=413, detail="result image too large") from error
        raise HTTPException(status_code=502, detail="result image fetch failed") from error
    except (httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail="result image fetch failed") from error

    content_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if not content_type.startswith("image/") or not content:
        raise HTTPException(status_code=415, detail="result image content is invalid")

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.get("/v1/results/{result_id}/image")
async def result_image(
    result_id: int,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> Response:
    result = db.scalar(
        select(Result)
        .join(Job, Result.job_id == Job.id)
        .where(
            Result.id == result_id,
            Result.rank > 0,
            Job.account_id == principal.account_id,
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="result image not available")
    return await _proxy_result_image(result)


@app.get("/v1/result-images/{result_id}")
async def result_image_capability(
    result_id: int,
    token: str = Query(min_length=20, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    result = db.scalar(
        select(Result).where(
            Result.id == result_id,
            Result.rank > 0,
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="result image not available")

    evidence = result.evidence if isinstance(result.evidence, dict) else {}
    expected = str(evidence.get("image_proxy_token") or "")
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=404, detail="result image not available")

    return await _proxy_result_image(result)
