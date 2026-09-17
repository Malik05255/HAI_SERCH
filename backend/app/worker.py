import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .budget import budget_for_job
from .config import settings
from .database import Base, SessionLocal, engine
from .media import delete_uploaded_media, enrich_query
from .models import Result
from .queue import claim_next_job, requeue
from .research import run_research


def utcnow():
    return datetime.now(timezone.utc)


def purge_job_media(job) -> None:
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None


def finish_job(db, job, status: str, progress: float | None = None, purge_media: bool = True) -> None:
    job.status = status
    if progress is not None:
        job.progress = progress
    if purge_media:
        purge_job_media(job)
    db.commit()


def process_one() -> bool:
    with SessionLocal() as db:
        job = claim_next_job(db)
        if job is None:
            return False
        if job.archived:
            purge_job_media(job)
            db.commit()
            return True
        if job.stop_requested:
            finish_job(db, job, "stopped", purge_media=False)
            return True

        budget = budget_for_job(job.attempts - 1)
        effective_query = enrich_query(job.query, job.input_url, job.input_type, budget.video_keyframes)
        if not effective_query:
            finish_job(db, job, "needs_context")
            return True

        try:
            candidates = asyncio.run(run_research(effective_query, job.attempts - 1, budget))
            db.refresh(job)
            if job.archived or job.status == "cancelled":
                purge_job_media(job)
                db.commit()
                return True

            existing = {r.url: r for r in db.scalars(select(Result).where(Result.job_id == job.id)).all()}
            for candidate in candidates:
                if candidate.url in existing:
                    result = existing[candidate.url]
                    if candidate.score > result.match_score:
                        result.match_score = candidate.score
                        result.summary = candidate.summary
                    continue
                result = Result(
                    job_id=job.id,
                    title=candidate.title,
                    url=candidate.url,
                    image_url=candidate.image_url,
                    summary=candidate.summary,
                    match_score=candidate.score,
                    evidence={
                        "verified_page": bool(candidate.summary),
                        "attempt": job.attempts,
                        "media_enriched": effective_query != job.query,
                    },
                )
                db.add(result)
                existing[candidate.url] = result

            db.flush()
            all_results = list(db.scalars(select(Result).where(Result.job_id == job.id).order_by(Result.match_score.desc())).all())
            top = all_results[: job.target_results]
            for index, result in enumerate(top, start=1):
                result.rank = index

            job.found_count = len(top)
            job.progress = min(1.0, job.found_count / max(job.target_results, 1))
            job.heartbeat_at = utcnow()

            if job.stop_requested:
                finish_job(db, job, "stopped", purge_media=False)
            elif job.found_count >= job.target_results:
                finish_job(db, job, "completed", 1.0)
            elif job.attempts >= settings.search_max_attempts:
                finish_job(db, job, "partial")
            else:
                db.commit()
                requeue(db, job)
        except Exception:
            db.refresh(job)
            if job.archived or job.status == "cancelled":
                purge_job_media(job)
                db.commit()
            elif job.stop_requested:
                finish_job(db, job, "stopped", purge_media=False)
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
