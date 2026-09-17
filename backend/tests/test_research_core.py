from collections import Counter
import io

from PIL import Image, ImageDraw

from app.models import Job, Result
from app.research import (
    Candidate,
    _best_overlap,
    _candidate_from_item,
    _canonical_http_url,
    _has_verifiable_evidence,
    _image_hash_variants,
    _preliminary_candidates,
    _visual_match,
    make_queries,
    overlap_score,
)
from app.worker import (
    _diverse_order,
    _effective_query,
    _image_capability,
    _merge_stronger_evidence,
    _safe_error,
)


def _result(title: str, url: str, score: float) -> Result:
    return Result(
        job_id="job-test",
        title=title,
        url=url,
        image_url=None,
        summary="",
        match_score=score,
        evidence={},
    )


def _candidate(name: str, score: float, *, with_image: bool = False) -> Candidate:
    return Candidate(
        title=name,
        url=f"https://example.com/{name}",
        image_url=f"https://images.example/{name}.jpg" if with_image else None,
        snippet="",
        summary="",
        score=score,
    )


def test_multilingual_query_expansion_keeps_exact_evidence() -> None:
    query = "فيلم صيني البطل في النهاية لا يتزوج البطلة"
    queries = make_queries(query, attempt=0)

    assert query in queries
    assert f'"{query}"' in queries
    assert any("剧情" in item for item in queries)
    assert any("结局" in item for item in queries)
    assert any("ending" in item for item in queries)


def test_overlap_score_is_token_based() -> None:
    assert overlap_score("red car city", "A red car reached the city") == 1.0
    assert overlap_score("red car city", "Only a red bicycle") < 0.5


def test_best_overlap_accepts_translated_planner_evidence() -> None:
    queries = [
        "فيلم صيني البطل لا يتزوج البطلة",
        "Chinese movie hero does not marry heroine",
        "男主角 最后 没有 娶 女主角",
    ]
    chinese_source = "故事结局 男主角 最后 没有 娶 女主角 两人分开"

    assert overlap_score(queries[0], chinese_source) == 0.0
    assert _best_overlap(queries, chinese_source) > 0.5


def test_effective_query_includes_live_context_without_changing_title_query() -> None:
    job = Job(
        query="فيلم صيني قديم",
        context_text="البطل يعمل طبيبًا والنهاية في محطة قطار",
        context_revision=2,
    )
    effective = _effective_query(
        job,
        {"ocr": "字幕 1998", "transcript": "goodbye", "vision": "railway platform"},
    )

    assert job.query == "فيلم صيني قديم"
    assert "البطل يعمل طبيبًا" in effective
    assert "字幕 1998" in effective
    assert "goodbye" in effective
    assert "railway platform" in effective


def test_visual_hash_exact_match_scores_maximum() -> None:
    score, distance = _visual_match(["0000000000000000"], "0000000000000000")
    assert distance == 0
    assert score == 100.0


def test_visual_match_uses_best_candidate_variant() -> None:
    score, distance = _visual_match(
        ["0000000000000000"],
        ["ffffffffffffffff", "0000000000000000"],
    )

    assert distance == 0
    assert score == 100.0


def test_result_image_hashes_include_full_and_centered_variants() -> None:
    image = Image.new("RGB", (200, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 25, 165, 115), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    hashes = _image_hash_variants(buffer.getvalue())

    assert 1 <= len(hashes) <= 3
    assert all(len(value) == 16 for value in hashes)


def test_media_preliminary_budget_keeps_low_text_image_candidates() -> None:
    candidates = [
        _candidate("text-a", 0.99),
        _candidate("text-b", 0.95),
        _candidate("text-c", 0.90),
        _candidate("visual-late", 0.01, with_image=True),
        _candidate("visual-later", 0.0, with_image=True),
    ]
    raw = {candidate.url: candidate for candidate in candidates}

    selected = _preliminary_candidates(raw, verify_pages=2, has_visual_refs=True)
    urls = {candidate.url for candidate in selected}

    assert len(selected) == 4
    assert candidates[0].url in urls
    assert candidates[1].url in urls
    assert candidates[3].url in urls
    assert candidates[4].url in urls


def test_text_only_preliminary_budget_remains_text_ranked() -> None:
    candidates = [
        _candidate("low-image", 0.01, with_image=True),
        _candidate("high", 0.99),
        _candidate("medium", 0.60),
    ]
    raw = {candidate.url: candidate for candidate in candidates}

    selected = _preliminary_candidates(raw, verify_pages=1, has_visual_refs=False)

    assert [candidate.title for candidate in selected] == ["high", "medium"]


def test_canonical_url_drops_tracking_without_losing_meaningful_query() -> None:
    canonical = _canonical_http_url(
        "HTTPS://Example.COM/movie?id=42&utm_source=newsletter&fbclid=abc#comments"
    )

    assert canonical == "https://example.com/movie?id=42"


def test_candidate_normalizes_relative_image_and_source_tracking() -> None:
    candidate = _candidate_from_item(
        {
            "url": "https://example.com/review?utm_campaign=test&id=7",
            "title": "Review",
            "img_src": "/images/poster.jpg?utm_source=feed",
            "content": "plot details",
        }
    )

    assert candidate is not None
    assert candidate.url == "https://example.com/review?id=7"
    assert candidate.image_url == "https://example.com/images/poster.jpg"


def test_canonical_url_rejects_credentials_and_non_http_schemes() -> None:
    assert _canonical_http_url("https://alice:secret@example.com/private") == ""
    assert _canonical_http_url("file:///etc/passwd") == ""


def test_stronger_visual_evidence_replaces_older_text_only_evidence() -> None:
    current = {
        "verified_page": True,
        "visual_match": False,
        "visual_score": 0.0,
        "image_proxy_token": "existing-token",
    }
    incoming = {
        "verified_page": False,
        "visual_match": True,
        "visual_score": 94.0,
        "visual_distance": 3,
    }

    merged, changed = _merge_stronger_evidence(current, incoming)

    assert changed is True
    assert merged["visual_match"] is True
    assert merged["visual_score"] == 94.0
    assert merged["image_proxy_token"] == "existing-token"


def test_weaker_evidence_does_not_replace_stronger_existing_evidence() -> None:
    current = {
        "verified_page": True,
        "visual_match": True,
        "visual_score": 97.0,
        "image_proxy_token": "existing-token",
    }
    incoming = {
        "verified_page": False,
        "visual_match": False,
        "visual_score": 10.0,
        "image_proxy_token": "new-token",
    }

    merged, changed = _merge_stronger_evidence(current, incoming)

    assert changed is False
    assert merged == current


def test_safe_error_redacts_url_credentials_and_limits_output() -> None:
    error = RuntimeError("request failed at https://alice:supersecret@example.com/private " + "x" * 500)
    rendered = _safe_error(error)

    assert "supersecret" not in rendered
    assert "alice" not in rendered
    assert "https://***@example.com/private" in rendered
    assert len(rendered) <= 300


def test_image_capability_is_random_only_for_public_result_images() -> None:
    first = _image_capability(None, "https://images.example/poster.jpg")
    second = _image_capability(None, "https://images.example/poster.jpg")

    assert first
    assert second
    assert first != second
    assert len(first) >= 24
    assert _image_capability(None, None) is None
    assert _image_capability(None, "file:///tmp/poster.jpg") is None


def test_image_capability_preserves_existing_token() -> None:
    result = _result("Movie", "https://example.com/movie", 91)
    result.image_url = "https://images.example/poster.jpg"
    result.evidence = {"image_proxy_token": "existing-capability-token-12345"}

    assert _image_capability(result, "https://other.example/new.jpg") == "existing-capability-token-12345"


def test_diverse_order_limits_duplicate_titles_and_domains_in_top_results() -> None:
    results = [
        _result("Same Movie", "https://example.com/a", 99),
        _result("Same Movie", "https://example.com/b", 98),
        _result("Different review", "https://example.com/c", 97),
        _result("Independent source", "https://other.example/d", 96),
        _result("Another source", "https://third.example/e", 95),
    ]

    ordered = _diverse_order(results, target=4)
    top = ordered[:4]
    titles = [item.title.casefold() for item in top]
    domains = [item.url.split("/")[2].removeprefix("www.") for item in top]

    assert len(top) == 4
    assert len(titles) == len(set(titles))
    assert max(Counter(domains).values()) <= 2
    assert top[0].url == "https://example.com/a"


def test_unverified_search_snippet_is_not_publishable_without_page_or_visual_match() -> None:
    candidate = _candidate("snippet-only", 0.9)
    candidate.visual_distance = None

    assert _has_verifiable_evidence(candidate, "") is False


def test_opened_source_page_is_verifiable_evidence() -> None:
    candidate = _candidate("page-backed", 0.9)

    assert _has_verifiable_evidence(candidate, "full extracted source page") is True


def test_strong_visual_match_can_verify_when_source_page_is_blocked() -> None:
    candidate = _candidate("visual-backed", 0.9, with_image=True)
    candidate.visual_distance = 2

    assert _has_verifiable_evidence(candidate, "") is True
