from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class ResearchBudget:
    max_candidates: int
    verify_pages: int
    http_concurrency: int = 6
    browser_pages: int = 4
    video_keyframes: int = 12


def budget_for_job(attempt: int) -> ResearchBudget:
    widening = min(attempt // 4, 3)
    return ResearchBudget(
        max_candidates=min(settings.search_max_candidates, 120 + widening * 40),
        verify_pages=min(settings.search_verify_pages_per_run + widening * 5, 60),
        http_concurrency=6,
        browser_pages=min(4 + widening, 8),
        video_keyframes=settings.video_max_keyframes,
    )
