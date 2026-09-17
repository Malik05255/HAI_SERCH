import asyncio
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from .budget import budget_for_job
from .config import settings
from .database import Base, SessionLocal, engine
from .media import delete_uploaded_media, media_features
from .models import Result
from .planner import plan_queries
from .queue import claim_next_job, requeue
from .research import run_research


TITLE_TOKEN_RE = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
CREDENTIAL_URL_RE = re.compile(r"://[^@\s]+@")


def utcnow():
    return datetime.now(timezone.utc)


def _safe_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    detail = CREDENTIAL_URL_RE.sub("://***@", detail)
    name = type(error).__name__
    if not detail:
        return name[:300]
    return f"{name}: {detail}"[:300]


def purge_job_media(job) -> None:
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None


def finish_job(db, job, status: str, progress: float | None = None, purge_media: bool = False) -> None:
    """Finish a job while retaining cloud media unless this is an explicit destructive action."""
    job.status = status
    if progress is not None:
        job.progress = progress
    if purge_media:
        purge_job_media(job)
    db.commit()


def _effective_query(job, features: dict) -> str:
    parts = [
        part.strip()
        for part in (
            job.query,
            features.get("ocr", ""),
            features.get("transcript", ""),
            features.get("vision", ""),
        )
        if part and part.strip()
    ]
    return " ".join(parts)[:12000]


def _title_key(value: str) -> str:
    return TITLE_TOKEN_RE.sub(" ", value.casefold()).strip()[:180]


def _domain(value: str) -> str:
    try:
        host = urlparse(value).netloc.casefold().split(":", 1)[0]
        return host.removeprefix("www.")
    except Exception:
        return ""


def _diverse_order(results: list[Result], target: int) -> list[Result]:
    """Put distinct, high-quality sources first without discarding useful evidence."""
    if not results:
        return []

    selected: list[Result] = []
    deferred: list[Result] = []
    domains: defaultdict[str, int] = defaultdict(int)
    seen_titles: set[str] = set()

    for result in results:
        domain = _domain(result.url)
        title_key = _title_key(result.title)
        duplicate_title = bool(title_key and title_key in seen_titles)
        domain_full = bool(domain and domains[domain] >= 2)

        if len(selected) < target and not duplicate_title and not domain_full:
            selected.append(result)
            if domain:
                domains[domain] += 1
            if title_key:
                seen_titles.add(title_key)
        else:
            deferred.append(result)

    if len(selected) < target:
        needed = target - len(selected)
        selected.extend(deferred[:needed])
        deferred = deferred[needed:]

    return selected + deferred


def process_one() -> bool:
    with SessionLocal() as db:
        job = claim_next_job(db)
        if job is None:
            return False
        if job.stop_requested:
            finish_job(db, job, "stopped")
            return True

        budget = budget_for_job(job.attempts - 1)
        features = media_features(job.input_url, job.input_type, budget.video_keyframes)

        if job.input_type in {"image", "video"} and settings.vision_enabled and not features.get("vision"):
            job.last_error = "visual_analysis_unavailable"
            if job.attempts >= settings.search_max_attempts:
                finish_job(db, job, "failed")
            else:
                db.commit()
                requeue(db, job)
            return True

        effective_query = _effective_query(job, features)
        hashes = list(features.get("hashes", []))
        if not effective_query:
            job.last_error = "insufficient_context"
            finish_job(db, job, "needs_context")
            return True

        planned_queries = plan_queries(effective_query)

        try:
            candidates = asyncio.run(
                run_research(
                    effective_query,
                    job.attempts - 1,
                    budget,
                    reference_hashes=hashes,
                    planned_queries=planned_queries,
                )
            )
            db.refresh(job)
            if job.status == "cancelled":
                purge_job_media(job)
                db.commit()
                return True
            if job.stop_requested:
                finish_job(db, job, "stopped")
                return True

            existing = {r.url: r for r in db.scalars(select(Result).where(Result.job_id == job.id)).all()}
            for candidate in candidates:
                evidence = {
                    "verified_page": candidate.page_verified,
                    "attempt": job.attempts,
                    "planner_used": bool(planned_queries),
                    "media_enriched": bool(features.get("ocr") or features.get("transcript") or features.get("vision")),
                    "vision_used": bool(features.get("vision")),
                    "speech_used": bool(features.get("transcript")),
                    "ocr_used": bool(features.get("ocr")),
                    "visual_score": candidate.visual_score,
                    "visual_distance": candidate.visual_distance,
                    "visual_match": candidate.visual_distance is not None
                    and candidate.visual_distance <= settings.visual_hash_max_distance,
                }
                if candidate.url in existing:
                    result = existing[candidate.url]
                    if candidate.score > result.match_score:
                        result.match_score = candidate.score
                        result.summary = candidate.summary
                        result.evidence = evidence
                    continue
                result = Result(
                    job_id=job.id,
                    title=candidate.title,
                    url=candidate.url,
                    image_url=candidate.image_url,
                    summary=candidate.summary,
                    match_score=candidate.score,
                    evidence=evidence,
                )
                db.add(result)
                existing[candidate.url] = result

            db.flush()
            all_results = list(
                db.scalars(
                    select(Result)
                    .where(Result.job_id == job.id)
                    .order_by(Result.match_score.desc(), Result.id.asc())
                ).all()
            )
            ordered = _diverse_order(all_results, job.target_results)
            for index, result in enumerate(ordered, start=1):
                result.rank = index
            top = ordered[: job.target_results]

            job.found_count = len(top)
            job.progress = min(1.0, job.found_count / max(job.target_results, 1))
            job.heartbeat_at = utcnow()
            job.last_error = None

            if job.found_count >= job.target_results:
                finish_job(db, job, "completed", 1.0)
            elif job.attempts >= settings.search_max_attempts:
                finish_job(db, job, "partial")
            else:
                db.commit()
                requeue(db, job)
        except Exception as error:
            db.refresh(job)
            job.last_error = _safe_error(error)
            if job.status == "cancelled":
                purge_job_media(job)
                db.commit()
            elif job.stop_requested:
                finish_job(db, job, "stopped")
            elif job.attempts >= settings.search_max_attempts:
                finish_job(db, job, "failed")
            else:
                job.status = "queued"
                db.commit()
                requeue(db, job)
        return True


def main() -> None:
    Base.metadata.create_all(bind=engine)
    while True:
        worked = process_one()
        if not worked:
            time.sleep(settings.search_idle_sleep_seconds)


if __name__ == "__main__":
    main()
