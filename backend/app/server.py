import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_principal
from .config import settings
from .database import get_db
from .egress import EgressRouter
from .main import app
from .models import Device, Job, Result


RESULT_IMAGE_MAX_BYTES = 6 * 1024 * 1024


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
    if result is None or not (result.image_url or "").strip():
        raise HTTPException(status_code=404, detail="result image not available")

    timeout = httpx.Timeout(settings.search_http_timeout_seconds)
    headers = {
        "User-Agent": "DeepSearch/0.10 (+result image proxy)",
        "Accept": "image/*",
    }
    try:
        async with EgressRouter(timeout=timeout, headers=headers) as egress:
            upstream, content = await egress.get_bytes(
                result.image_url,
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
        },
    )
