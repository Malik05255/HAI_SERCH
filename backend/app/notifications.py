import base64
import json
from functools import lru_cache

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Device, Job


FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


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


def send_job_pushes(db: Session, job: Job) -> bool:
    """Send a terminal job notification. Failures never affect research state."""
    firebase = _firebase_credentials()
    if firebase is None or not job.account_id:
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
    success = False
    changed = False

    with httpx.Client(timeout=12.0, headers=headers) as client:
        for device in devices:
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
                    success = True
                    continue
                if response.status_code in {400, 404} and "UNREGISTERED" in response.text.upper():
                    device.push_token = None
                    changed = True
            except Exception:
                continue

    if changed:
        db.commit()
    return success or changed
