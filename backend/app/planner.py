from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx

from .config import settings


PLANNER_PROMPT = """You are a web-search query planner. Convert the evidence below into high-precision search queries.
Rules:
- Return ONLY a JSON array of strings, no markdown.
- Maximum {max_queries} queries.
- Do not invent names, titles, dates, actors, places, or facts not supported by the evidence.
- Preserve exact names, quoted dialogue, OCR text, and uncertainty.
- Use the original language when useful and add English translations/search wording.
- If the evidence strongly indicates another language/country (for example Chinese/Japanese/Korean), include useful queries in that language too.
- Keep each query under 220 characters.

Evidence:
{evidence}
"""


def _cache_path(evidence: str) -> Path:
    digest = hashlib.sha256(evidence.encode("utf-8", errors="ignore")).hexdigest()
    root = Path(settings.data_dir, "cache", "planner")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{digest}.json"


def _load_cache(path: Path) -> list[str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        values = [" ".join(str(item).split())[:220] for item in data if str(item).strip()]
        return values[: settings.planner_max_queries]
    except Exception:
        return None


def _parse_json_array(text: str) -> list[str]:
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for raw in data:
        value = " ".join(str(raw).split())[:220]
        value = re.sub(r"^[\-•\d.\s]+", "", value).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
        if len(output) >= settings.planner_max_queries:
            break
    return output


def plan_queries(evidence: str) -> list[str]:
    evidence = " ".join(evidence.split())[:10000]
    if not evidence or not settings.planner_enabled:
        return []

    cache = _cache_path(evidence)
    cached = _load_cache(cache)
    if cached is not None:
        return cached

    prompt = PLANNER_PROMPT.format(max_queries=settings.planner_max_queries, evidence=evidence)
    payload = {
        "messages": [
            {"role": "system", "content": "Generate search queries only from supplied evidence."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 420,
    }
    try:
        response = httpx.post(
            f"{settings.planner_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            timeout=settings.planner_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        queries = _parse_json_array(str(content))
        if queries:
            try:
                cache.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return queries
    except Exception:
        return []
