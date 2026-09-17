from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import Principal, require_principal
from .database import get_db
from .main import app
from .models import Device


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
