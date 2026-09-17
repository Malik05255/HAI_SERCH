import base64
import json
from datetime import datetime, timezone
from functools import lru_cache

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Device, Job, NotificationDelivery


FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TERMINAL_DELIVERY_STATES = {"sent", "discarded"}


def notification_text(job: Job) -> tuple[str, str]:
    title = "البحث العميق"
    if job.status == "completed":
        return title, f"اكتمل البحث وتم العثور على {job.found_count} من {job.target_results} نتائج."
    if job.status == "partial":
        return title, f"انتهى البحث بـ {job.found_count} من {job.target_results} نتائج موثوقة."
    if job.status == "needs_context":
        return title, "توقف البحث لأن الأدلة الحالية غير كافية. أضف معلومة أوضح ثم تابع البحث."
    return title, "تعذر إكمال البحث الحالي. يمكنك فتح المهمة والمحاولة مرة أخرى."


@lru_cache(maxsize=1)
def _firebase_credentials():
    if not settings.notifications_enabled or not settings.firebase_service_account_b64.strip():
        return None
    try:
        decoded = base64.b64decode(settings.firebase_service_account_b64).decode("utf-8")
        info = json.loads(decoded)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[FCM_SCOPE],
        )
        project_id = settings.firebase_project_id.strip() or str(info.get("project_id") or "").strip()
        if not project_id:
            return None
        return credentials, project_id
    except Exception:
        return None


def _delivery_map(db: Session, job_id: str) -> dict[str, NotificationDelivery]:
    rows = list(
        db.scalars(
            select(NotificationDelivery).where(NotificationDelivery.job_id == job_id)
        ).all()
    )
    return {row.device_id: row for row in rows}


def send_job_pushes(db: Session, job: Job) -> bool:
    """Deliver completion notifications independently to each registered device.

    A successful device is persisted as ``sent`` and is never notified again for
    this completion cycle. Invalid tokens become ``discarded``. Transient failures
    remain ``pending`` so the runtime retries only those devices after restarts.
    """
    if not settings.notifications_enabled or not job.account_id:
        return True

    devices = list(
        db.scalars(
            select(Device).where(
                Device.account_id == job.account_id,
                Device.push_token.is_not(None),
            )
        ).all()
    )
    devices = [device for device in devices if (device.push_token or "").strip()]
    if not devices:
        return True

    deliveries = _delivery_map(db, job.id)
    created = False
    for device in devices:
        if device.id in deliveries:
            continue
        delivery = NotificationDelivery(job_id=job.id, device_id=device.id, state="pending")
        db.add(delivery)
        deliveries[device.id] = delivery
        created = True
    if created:
        db.commit()

    pending_devices = [
        device
        for device in devices
        if deliveries[device.id].state not in _TERMINAL_DELIVERY_STATES
    ]
    if not pending_devices:
        return True

    firebase = _firebase_credentials()
    if firebase is None:
        return False

    credentials, project_id = firebase
    try:
        if not credentials.valid:
            credentials.refresh(Request())
        access_token = credentials.token
        if not access_token:
            return False
    except Exception:
        return False

    title, body = notification_text(job)
    endpoint = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    changed = False

    with httpx.Client(timeout=12.0, headers=headers) as client:
        for device in pending_devices:
            delivery = deliveries[device.id]
            payload = {
                "message": {
                    "token": device.push_token,
                    "notification": {"title": title, "body": body},
                    "data": {
                        "job_id": job.id,
                        "status": job.status,
                        "found_count": str(job.found_count),
                        "target_results": str(job.target_results),
                    },
                    "android": {"priority": "high"},
                }
            }
            try:
                response = client.post(endpoint, json=payload)
                if 200 <= response.status_code < 300:
                    delivery.state = "sent"
                    delivery.sent_at = datetime.now(timezone.utc)
                    changed = True
                    continue
                if response.status_code in {400, 404} and "UNREGISTERED" in response.text.upper():
                    device.push_token = None
                    delivery.state = "discarded"
                    changed = True
            except Exception:
                continue

    if changed:
        db.commit()

    return all(
        deliveries[device.id].state in _TERMINAL_DELIVERY_STATES
        for device in devices
    )
