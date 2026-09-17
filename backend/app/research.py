import asyncio
import io
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import imagehash
import trafilatura
from PIL import Image

from .budget import ResearchBudget
from .config import settings
from .egress import EgressRouter


TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
RESULT_IMAGE_MAX_BYTES = 6 * 1024 * 1024


@dataclass
class Candidate:
    title: str
    url: str
    image_url: str | None
    snippet: str
    summary: str
    score: float
    visual_score: float = 0.0
    visual_distance: int | None = None
    page_verified: bool = False


def tokens(text: str) -> set[str]:
    return {t.casefold() for t in TOKEN_RE.findall(text) if len(t) > 2}


def overlap_score(query: str, text: str) -> float:
    q = tokens(query)
    if not q:
        return 0.0
    t = tokens(text)
    return len(q & t) / len(q)


def _best_overlap(queries: list[str], text: str) -> float:
    if not text:
        return 0.0
    return max((overlap_score(query, text) for query in queries if query.strip()), default=0.0)


def _query_chunks(text: str) -> list[str]:
    clean = " ".join(text.split())
    if len(clean) <= 220:
        return [clean]
    size = 180
    chunks = [clean[:size], clean[-size:]]
    middle = max(0, len(clean) // 2 - size // 2)
    chunks.append(clean[middle : middle + size])
    seen: set[str] = set()
    unique: list[str] = []
    for chunk in chunks:
        if chunk and chunk not in seen:
            seen.add(chunk)
            unique.append(chunk)
    return unique


def make_queries(query: str, attempt: int, planned_queries: list[str] | None = None) -> list[str]:
    chunks = _query_chunks(query)
    base = chunks[0] if chunks else query.strip()
    queries = list(planned_queries or []) + list(chunks)

    for chunk in chunks:
        if 8 <= len(chunk) <= 180:
            queries.append(f'"{chunk}"')

    lowered = query.casefold()
    if any(x in lowered for x in ("فيلم", "مسلسل", "movie", "film", "series")):
        queries.extend([f"{base} plot", f"{base} ending", f"{base} ending explained"])
    if "صيني" in lowered or "chinese" in lowered:
        queries.extend([f"{base} 剧情", f"{base} 结局"])
    if attempt >= 4:
        queries.extend([f"{base} review", f"{base} discussion"])
    if attempt >= 8:
        queries.extend([f"{base} recap", f"{base} synopsis"])

    seen: set[str] = set()
    unique: list[str] = []
    for item in queries:
        item = " ".join(item.split())[:500]
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


async def _searx(
    query: str,
    page: int,
    client: httpx.AsyncClient,
    categories: str | None = None,
) -> list[dict]:
    params = {"q": query, "format": "json", "language": "all", "pageno": page}
    if categories:
        params["categories"] = categories
    response = await client.get(
        f"{settings.searxng_url.rstrip('/')}/search",
        params=params,
    )
    response.raise_for_status()
    return response.json().get("results", [])


async def _fetch_page(url: str, egress: EgressRouter, sem: asyncio.Semaphore) -> str:
    async with sem:
        try:
            response = await egress.get(url)
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            extracted = trafilatura.extract(response.text, include_comments=False, include_tables=False)
            return extracted or ""
        except Exception:
            return ""


def _image_hash_variants(content: bytes) -> list[str]:
    """Hash full image plus centered crops to tolerate thumbnail cropping/borders."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            image = image.convert("RGB")
            width, height = image.size
            variants = [image]
            for ratio in (0.86, 0.72):
                crop_w = max(16, int(width * ratio))
                crop_h = max(16, int(height * ratio))
                left = max(0, (width - crop_w) // 2)
                top = max(0, (height - crop_h) // 2)
                variants.append(image.crop((left, top, left + crop_w, top + crop_h)))

            hashes: list[str] = []
            for variant in variants:
                value = str(imagehash.phash(variant))
                if value not in hashes:
                    hashes.append(value)
            return hashes
    except Exception:
        return []


async def _image_phashes(url: str | None, egress: EgressRouter, sem: asyncio.Semaphore) -> list[str]:
    if not url or not url.startswith(("http://", "https://")):
        return []
    async with sem:
        try:
            response, content = await egress.get_bytes(url, max_bytes=RESULT_IMAGE_MAX_BYTES)
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/") or not content:
                return []
            return _image_hash_variants(content)
        except Exception:
            return []


def _visual_match(
    reference_hashes: list[str],
    candidate_hashes: str | list[str],
) -> tuple[float, int | None]:
    if not reference_hashes:
        return 0.0, None
    if isinstance(candidate_hashes, str):
        candidate_values = [candidate_hashes] if candidate_hashes else []
    else:
        candidate_values = [value for value in candidate_hashes if value]
    if not candidate_values:
        return 0.0, None

    try:
        references = [imagehash.hex_to_hash(value) for value in reference_hashes]
        candidates = [imagehash.hex_to_hash(value) for value in candidate_values]
        distance = min(candidate - reference for candidate in candidates for reference in references)
        score = max(0.0, 1.0 - distance / 64.0) * 100.0
        return round(score, 2), distance
    except Exception:
        return 0.0, None


def _candidate_from_item(item: dict) -> Candidate | None:
    url = item.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return None
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    image_url = (
        item.get("img_src")
        or item.get("thumbnail_src")
        or item.get("thumbnail")
        or item.get("image")
    )
    return Candidate(
        title=(item.get("title") or parsed.netloc).strip(),
        url=url,
        image_url=image_url,
        snippet=(item.get("content") or item.get("source") or "").strip(),
        summary="",
        score=0.0,
    )


async def run_research(
    query: str,
    attempt: int,
    budget: ResearchBudget,
    reference_hashes: list[str] | None = None,
    planned_queries: list[str] | None = None,
) -> list[Candidate]:
    reference_hashes = reference_hashes or []
    timeout = httpx.Timeout(settings.search_http_timeout_seconds)
    headers = {"User-Agent": "DeepSearch/0.6 (+personal research assistant)"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as search_client:
        async with EgressRouter(timeout=timeout, headers=headers) as egress:
            raw: dict[str, Candidate] = {}
            page = min(5, 1 + attempt // 3)
            queries = make_queries(query, attempt, planned_queries=planned_queries)
            successful_search_requests = 0

            for query_index, search_query in enumerate(queries):
                batches: list[list[dict]] = []
                try:
                    batches.append(await _searx(search_query, page, search_client))
                    successful_search_requests += 1
                except Exception:
                    pass

                if reference_hashes and query_index < 6:
                    try:
                        batches.append(await _searx(search_query, min(page, 2), search_client, categories="images"))
                        successful_search_requests += 1
                    except Exception:
                        pass

                for items in batches:
                    for item in items:
                        candidate = _candidate_from_item(item)
                        if candidate is None:
                            continue
                        text = f"{candidate.title} {candidate.snippet}"
                        retrieval_score = max(
                            overlap_score(query, text),
                            overlap_score(search_query, text),
                        )
                        if candidate.url in raw:
                            existing = raw[candidate.url]
                            existing.score = max(existing.score, retrieval_score)
                            if not existing.image_url and candidate.image_url:
                                existing.image_url = candidate.image_url
                            continue
                        candidate.score = retrieval_score
                        raw[candidate.url] = candidate
                        if len(raw) >= budget.max_candidates:
                            break
                    if len(raw) >= budget.max_candidates:
                        break
                if len(raw) >= budget.max_candidates:
                    break

            if queries and successful_search_requests == 0:
                raise RuntimeError("search_backend_unavailable")

            prelim = sorted(raw.values(), key=lambda c: c.score, reverse=True)[: max(budget.verify_pages * 2, budget.verify_pages)]
            sem = asyncio.Semaphore(budget.http_concurrency)

            if reference_hashes:
                image_hashes = await asyncio.gather(*[_image_phashes(c.image_url, egress, sem) for c in prelim])
                for candidate, fingerprints in zip(prelim, image_hashes):
                    candidate.visual_score, candidate.visual_distance = _visual_match(reference_hashes, fingerprints)

            ranked = sorted(
                prelim,
                key=lambda c: (
                    c.visual_distance is not None and c.visual_distance <= settings.visual_hash_max_distance,
                    c.visual_score * 0.65 + c.score * 100 * 0.35,
                ),
                reverse=True,
            )[: budget.verify_pages]
            texts = await asyncio.gather(*[_fetch_page(c.url, egress, sem) for c in ranked])

    verified: list[Candidate] = []
    for candidate, page_text in zip(ranked, texts):
        snippet_score = _best_overlap(queries, f"{candidate.title} {candidate.snippet}") * 100.0
        page_score = _best_overlap(queries, page_text[:12000]) * 100.0 if page_text else 0.0
        text_score = snippet_score * 0.35 + page_score * 0.65
        if candidate.visual_distance is not None:
            if candidate.visual_distance <= settings.visual_hash_max_distance:
                combined = candidate.visual_score * 0.72 + text_score * 0.28
            else:
                combined = candidate.visual_score * 0.35 + text_score * 0.65
        else:
            combined = text_score
        candidate.score = round(min(100.0, combined), 2)
        candidate.page_verified = bool(page_text)
        candidate.summary = " ".join(page_text.split())[:700] if page_text else candidate.snippet[:700]
        if candidate.score >= settings.search_min_result_score:
            verified.append(candidate)

    return sorted(verified, key=lambda c: c.score, reverse=True)
