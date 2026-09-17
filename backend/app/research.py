import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from .budget import ResearchBudget
from .config import settings


TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)


@dataclass
class Candidate:
    title: str
    url: str
    image_url: str | None
    snippet: str
    summary: str
    score: float


def tokens(text: str) -> set[str]:
    return {t.casefold() for t in TOKEN_RE.findall(text) if len(t) > 2}


def overlap_score(query: str, text: str) -> float:
    q = tokens(query)
    if not q:
        return 0.0
    t = tokens(text)
    return len(q & t) / len(q)


def make_queries(query: str, attempt: int) -> list[str]:
    base = query.strip()
    queries = [base]
    if len(base) < 180:
        queries.append(f'"{base}"')

    lowered = base.casefold()
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
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


async def _searx(query: str, page: int, client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(
        f"{settings.searxng_url.rstrip('/')}/search",
        params={"q": query, "format": "json", "language": "all", "pageno": page},
    )
    response.raise_for_status()
    return response.json().get("results", [])


async def _fetch_page(url: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> str:
    async with sem:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            extracted = trafilatura.extract(response.text, include_comments=False, include_tables=False)
            return extracted or ""
        except Exception:
            return ""


async def run_research(query: str, attempt: int, budget: ResearchBudget) -> list[Candidate]:
    proxy = settings.egress_proxy_url or None
    timeout = httpx.Timeout(settings.search_http_timeout_seconds)
    headers = {"User-Agent": "DeepSearch/0.1 (+personal research assistant)"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, proxy=proxy) as client:
        raw: dict[str, Candidate] = {}
        page = min(5, 1 + attempt // 3)
        for search_query in make_queries(query, attempt):
            try:
                items = await _searx(search_query, page, client)
            except Exception:
                continue
            for item in items:
                url = item.get("url") or ""
                if not url.startswith(("http://", "https://")):
                    continue
                parsed = urlparse(url)
                if not parsed.netloc or url in raw:
                    continue
                raw[url] = Candidate(
                    title=(item.get("title") or parsed.netloc).strip(),
                    url=url,
                    image_url=item.get("img_src") or item.get("thumbnail"),
                    snippet=(item.get("content") or "").strip(),
                    summary="",
                    score=overlap_score(query, f"{item.get('title', '')} {item.get('content', '')}"),
                )
                if len(raw) >= budget.max_candidates:
                    break
            if len(raw) >= budget.max_candidates:
                break

        ranked = sorted(raw.values(), key=lambda c: c.score, reverse=True)[: budget.verify_pages]
        sem = asyncio.Semaphore(budget.http_concurrency)
        texts = await asyncio.gather(*[_fetch_page(c.url, client, sem) for c in ranked])

    verified: list[Candidate] = []
    for candidate, page_text in zip(ranked, texts):
        snippet_score = overlap_score(query, f"{candidate.title} {candidate.snippet}")
        page_score = overlap_score(query, page_text[:12000]) if page_text else 0.0
        candidate.score = round((snippet_score * 0.35 + page_score * 0.65) * 100, 2)
        candidate.summary = " ".join(page_text.split())[:700] if page_text else candidate.snippet[:700]
        verified.append(candidate)

    return sorted(verified, key=lambda c: c.score, reverse=True)
