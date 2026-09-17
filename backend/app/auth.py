import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Account, Device, PairCode


PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _new_pair_code() -> str:
    return "".join(secrets.choice(PAIR_ALPHABET) for _ in range(8))


@dataclass(frozen=True)
class Principal:
    account_id: str
    device_id: str


def principal_for_token(db: Session, token: str) -> Principal | None:
    normalized = token.strip()
    if not normalized:
        return None
    device = db.scalar(select(Device).where(Device.token_hash == _hash_token(normalized)))
    if device is None:
        return None
    return Principal(account_id=device.account_id, device_id=device.id)


def register_device(db: Session, name: str) -> dict:
    account = Account()
    db.add(account)
    db.flush()
    token = _new_token()
    device = Device(account_id=account.id, name=(name.strip() or "Device")[:120], token_hash=_hash_token(token))
    db.add(device)
    db.commit()
    return {"token": token, "device_id": device.id}


def create_pair_code(db: Session, principal: Principal) -> dict:
    now = utcnow()
    db.execute(delete(PairCode).where(PairCode.expires_at < now))
    for _ in range(8):
        code = _new_pair_code()
        if db.get(PairCode, code) is None:
            db.add(PairCode(code=code, account_id=principal.account_id, expires_at=now + timedelta(minutes=10)))
            db.commit()
            return {"code": code, "expires_in": 600}
    raise HTTPException(status_code=503, detail="pair code unavailable")


def pair_device(db: Session, code: str, name: str) -> dict:
    normalized = code.replace("-", "").replace(" ", "").upper()
    pair = db.get(PairCode, normalized)
    if pair is None or pair.expires_at < utcnow():
        if pair is not None:
            db.delete(pair)
            db.commit()
        raise HTTPException(status_code=400, detail="invalid or expired pair code")
    token = _new_token()
    device = Device(account_id=pair.account_id, name=(name.strip() or "Device")[:120], token_hash=_hash_token(token))
    db.add(device)
    db.delete(pair)
    db.commit()
    return {"token": token, "device_id": device.id}


def require_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing device token")
    principal = principal_for_token(db, authorization[7:])
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    return principal
