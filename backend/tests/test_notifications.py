from app.models import Job
from app.notifications import notification_text


def test_completed_notification_reports_result_count() -> None:
    job = Job(status="completed", found_count=10, target_results=10)
    title, body = notification_text(job)

    assert title == "البحث العميق"
    assert "10 من 10" in body


def test_partial_notification_is_distinct() -> None:
    job = Job(status="partial", found_count=6, target_results=10)
    _, body = notification_text(job)

    assert "6 من 10" in body
    assert "موثوقة" in body


def test_needs_context_notification_requests_more_evidence() -> None:
    job = Job(status="needs_context", found_count=0, target_results=10)
    _, body = notification_text(job)

    assert "غير كافية" in body
