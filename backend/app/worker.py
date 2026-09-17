import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .budget import budget_for_job
from .config import settings
from .database import Base, SessionLocal, engine
from .media import enrich_query
from .models import Result
from .queue import claim_next_job, requeue
from .research import run_research


def utcnow():
    return datetime.now(timezone.utc)


def process_one() -> bool:
    with SessionLocal() as db:
        job = claim_next_job(db)
        if job is None:
            return False
        if job.stop_requested:
            job.status = "stopped"
            db.commit()
            return True

        budget = budget_for_job(job.attempts - 1)
        effective_query = enrich_query(job.query, job.input_url, job.input_type, budget.video_keyframes)
        if not effective_query:
            job.status = "needs_context"
            db.commit()
            return True

        try:
            candidates = asyncio.run(run_research(effective_query, job.attempts - 1, budget))
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
                job.status = "stopped"
                db.commit()
            elif job.found_count >= job.target_results:
                job.status = "completed"
                job.progress = 1.0
                db.commit()
            elif job.attempts >= settings.search_max_attempts:
                job.status = "partial"
                db.commit()
            else:
                db.commit()
                requeue(db, job)
        except Exception:
            job.status = "queued" if job.attempts < settings.search_max_attempts else "failed"
            db.commit()
            if job.status == "queued":
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
