import asyncio
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from .budget import budget_for_job
from .config import settings
from .database import SessionLocal, ensure_schema
from .media import delete_uploaded_media, media_features
from .models import Job, Result
from .notifications import send_job_pushes
from .planner import plan_queries
from .queue import claim_next_job, requeue
from .research import run_research


TITLE_TOKEN_RE = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
CREDENTIAL_URL_RE = re.compile(r"://[^@\s]+@")
PUSH_COMPLETION_STATES = {"completed", "partial"}
PURGE_MEDIA_STATES = {"completed", "partial", "failed"}
YEAR_TOKEN_RE = re.compile(r"^(?:18|19|20|21)\d{2}$")
WORK_TITLE_NOISE = {
    "a", "an", "the",
    "film", "movie", "movies", "series", "tv", "show",
    "review", "reviews", "trailer", "official", "watch", "stream", "streaming",
    "episode", "season", "full", "hd",
    "imdb", "tmdb", "wikipedia", "netflix", "justwatch", "youtube",
    "فيلم", "افلام", "أفلام", "مسلسل", "مسلسلات",
    "مراجعة", "اعلان", "إعلان", "رسمي", "مشاهدة", "كامل",
    "حلقة", "الحلقة", "موسم", "الموسم",
}


def utcnow():
    return datetime.now(timezone.utc)


def _safe_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    detail = CREDENTIAL_URL_RE.sub("://***@", detail)
    name = type(error).__name__
    if not detail:
        return name[:300]
    return f"{name}: {detail}"[:300]


def _reload_job(db, job_id: str) -> Job | None:
    return db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .execution_options(populate_existing=True)
    )


def _requeue_now(db, job: Job) -> None:
    job.status = "queued"
    job.stop_requested = False
    job.next_run_at = utcnow()
    job.heartbeat_at = None
    job.last_error = None
    db.commit()


def purge_job_media(job) -> None:
    if job.input_url:
        delete_uploaded_media(job.input_url)
        job.input_url = None


def finish_job(db, job, status: str, progress: float | None = None) -> None:
    job.status = status
    if progress is not None:
        job.progress = progress
    job.heartbeat_at = None
    if status in PURGE_MEDIA_STATES:
        purge_job_media(job)

    should_notify = status in PUSH_COMPLETION_STATES and settings.notifications_enabled
    job.notification_pending = should_notify
    if should_notify:
        job.notification_sent_at = None
    db.commit()

    if not should_notify:
        return

    try:
        delivered = send_job_pushes(db, job)
    except Exception:
        delivered = False
    if delivered:
        job.notification_pending = False
        job.notification_sent_at = utcnow()
        db.commit()


def _effective_query(job, features: dict) -> str:
    parts = [
        part.strip()
        for part in (
            job.query,
            job.context_text,
            features.get("ocr", ""),
            features.get("transcript", ""),
            features.get("vision", ""),
        )
        if part and part.strip()
    ]
    return " ".join(parts)[:12000]


def _title_key(value: str) -> str:
    return TITLE_TOKEN_RE.sub(" ", value.casefold()).strip()[:180]


def _work_signature(value: str) -> tuple[tuple[str, ...], frozenset[str]]:
    """Return title identity tokens and explicit years without source/review noise."""
    tokens = [token for token in _title_key(value).split() if token]
    years = frozenset(token for token in tokens if YEAR_TOKEN_RE.fullmatch(token))
    core = tuple(
        token
        for token in tokens
        if token not in years and token not in WORK_TITLE_NOISE
    )
    return core, years


def _same_work_title(left: str, right: str) -> bool:
    """Conservatively identify two result pages that refer to the same work."""
    left_core, left_years = _work_signature(left)
    right_core, right_years = _work_signature(right)

    if left_years and right_years and left_years.isdisjoint(right_years):
        return False
    if not left_core or not right_core:
        return _title_key(left) == _title_key(right)
    if left_core == right_core:
        return True

    left_set = set(left_core)
    right_set = set(right_core)
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    if intersection < 2 or union == 0:
        return False
    return intersection / union >= 0.85


def _domain(value: str) -> str:
    try:
        host = urlparse(value).netloc.casefold().split(":", 1)[0]
        return host.removeprefix("www.")
    except Exception:
        return ""


def _evidence_quality(evidence: dict | None) -> tuple[int, float, int, int, int, int]:
    value = evidence if isinstance(evidence, dict) else {}
    return (
        1 if value.get("visual_match") is True else 0,
        float(value.get("visual_score") or 0.0),
        1 if value.get("verified_page") is True else 0,
        1 if value.get("vision_used") is True else 0,
        1 if value.get("speech_used") is True else 0,
        1 if value.get("ocr_used") is True else 0,
    )


def _merge_stronger_evidence(current: dict | None, incoming: dict) -> tuple[dict, bool]:
    existing = dict(current or {})
    incoming_value = dict(incoming)
    existing_token = str(existing.get("image_proxy_token") or "").strip()
    incoming_token = str(incoming_value.get("image_proxy_token") or "").strip()
    if existing_token and not incoming_token:
        incoming_value["image_proxy_token"] = existing_token

    replace = _evidence_quality(incoming_value) > _evidence_quality(existing)
    if replace:
        return incoming_value, True

    if incoming_token and not existing_token:
        existing["image_proxy_token"] = incoming_token
        return existing, True
    return existing, False


def _diverse_order(results: list[Result], target: int) -> list[Result]:
    """Choose unique works first; source diversity is soft, work diversity is hard."""
    if not results or target <= 0:
        return []

    selected: list[Result] = []
    domain_deferred: list[Result] = []
    domains: defaultdict[str, int] = defaultdict(int)

    def duplicates_selected(candidate: Result) -> bool:
        return any(_same_work_title(candidate.title, item.title) for item in selected)

    for result in results:
        if duplicates_selected(result):
            continue
        domain = _domain(result.url)
        if domain and domains[domain] >= 2:
            domain_deferred.append(result)
            continue

        selected.append(result)
        if domain:
            domains[domain] += 1
        if len(selected) >= target:
            return selected

    # Relax source concentration only when needed. A duplicate work is never
    # reinserted merely to make the UI show the requested number of results.
    for result in domain_deferred:
        if duplicates_selected(result):
            continue
        selected.append(result)
        if len(selected) >= target:
            break

    return selected


def _annotate_supporting_sources(results: list[Result], max_sources: int = 6) -> None:
    """Attach one representative URL per independent domain to the best page."""
    if not results:
        return

    # Remove stale aggregation from previous rounds before rebuilding it from
    # the currently credible result set.
    for result in results:
        evidence = dict(result.evidence or {})
        evidence.pop("supporting_source_count", None)
        evidence.pop("supporting_sources", None)
        result.evidence = evidence

    groups: list[list[Result]] = []
    for result in results:
        group = next(
            (
                existing
                for existing in groups
                if _same_work_title(result.title, existing[0].title)
            ),
            None,
        )
        if group is None:
            groups.append([result])
        else:
            group.append(result)

    for group in groups:
        primary = group[0]
        seen_domains: set[str] = set()
        sources: list[dict[str, str]] = []
        for result in group:
            domain = _domain(result.url)
            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)
            sources.append({"domain": domain, "url": result.url})
            if len(sources) >= max_sources:
                break

        evidence = dict(primary.evidence or {})
        evidence["supporting_source_count"] = len(sources)
        evidence["supporting_sources"] = sources
        primary.evidence = evidence


def _image_capability(existing_result: Result | None, candidate_image_url: str | None) -> str | None:
    current = ""
    if existing_result is not None and isinstance(existing_result.evidence, dict):
        current = str(existing_result.evidence.get("image_proxy_token") or "").strip()
    if current:
        return current
    image_url = (candidate_image_url or (existing_result.image_url if existing_result else None) or "").strip()
    if not image_url.startswith(("http://", "https://")):
        return None
    return secrets.token_urlsafe(24)


def process_one() -> bool:
    with SessionLocal() as db:
        job = claim_next_job(db)
        if job is None:
            return False
        job_id = job.id

        try:
            if job.stop_requested:
                finish_job(db, job, "stopped")
                return True

            budget = budget_for_job(job.attempts - 1)
            features = media_features(job.input_url, job.input_type, budget.video_keyframes)

            current = _reload_job(db, job_id)
            if current is None:
                db.rollback()
                return True
            job = current
            if job.status == "cancelled":
                purge_job_media(job)
                db.commit()
                return True
            if job.stop_requested:
                finish_job(db, job, "stopped")
                return True

            if job.input_type in {"image", "video"} and settings.vision_enabled and not features.get("vision"):
                job.last_error = "visual_analysis_unavailable"
                if job.attempts >= settings.search_max_attempts:
                    finish_job(db, job, "failed")
                else:
                    db.commit()
                    requeue(db, job)
                return True

            effective_query = _effective_query(job, features)
            context_revision = job.context_revision
            hashes = list(features.get("hashes", []))
            if not effective_query:
                job.last_error = "insufficient_context"
                finish_job(db, job, "needs_context")
                return True

            planned_queries = plan_queries(effective_query)
            candidates = asyncio.run(
                run_research(
                    effective_query,
                    job.attempts - 1,
                    budget,
                    reference_hashes=hashes,
                    planned_queries=planned_queries,
                )
            )

            current = _reload_job(db, job_id)
            if current is None:
                db.rollback()
                return True
            job = current
            if job.status == "cancelled":
                purge_job_media(job)
                db.commit()
                return True
            if job.stop_requested:
                finish_job(db, job, "stopped")
                return True
            if job.context_revision != context_revision:
                _requeue_now(db, job)
                return True

            existing = {r.url: r for r in db.scalars(select(Result).where(Result.job_id == job.id)).all()}
            for candidate in candidates:
                current_result = existing.get(candidate.url)
                image_proxy_token = _image_capability(current_result, candidate.image_url)
                evidence = {
                    "verified_page": candidate.page_verified,
                    "attempt": job.attempts,
                    "context_revision": context_revision,
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
                if image_proxy_token:
                    evidence["image_proxy_token"] = image_proxy_token

                if current_result is not None:
                    if candidate.image_url and not current_result.image_url:
                        current_result.image_url = candidate.image_url

                    stronger_evidence, evidence_changed = _merge_stronger_evidence(
                        current_result.evidence,
                        evidence,
                    )
                    score_improved = candidate.score > current_result.match_score
                    if score_improved:
                        current_result.match_score = candidate.score
                        current_result.summary = candidate.summary
                    elif evidence_changed and candidate.page_verified and candidate.summary:
                        current_result.summary = candidate.summary
                    if evidence_changed:
                        current_result.evidence = stronger_evidence
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
            credible_results = list(
                db.scalars(
                    select(Result)
                    .where(
                        Result.job_id == job.id,
                        Result.match_score >= settings.search_min_result_score,
                    )
                    .order_by(Result.match_score.desc(), Result.id.asc())
                ).all()
            )
            _annotate_supporting_sources(credible_results)
            ordered = _diverse_order(credible_results, job.target_results)
            top = ordered[: job.target_results]

            for result in existing.values():
                result.rank = 0
            for index, result in enumerate(top, start=1):
                result.rank = index

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
            db.rollback()
            current = _reload_job(db, job_id)
            if current is None:
                return True
            job = current
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
    ensure_schema()
    while True:
        worked = process_one()
        if not worked:
            time.sleep(settings.search_idle_sleep_seconds)


if __name__ == "__main__":
    main()
