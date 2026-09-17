from collections import Counter
import io

from PIL import Image, ImageDraw

from app.models import Job, Result
from app.research import _best_overlap, _image_hash_variants, _visual_match, make_queries, overlap_score
from app.worker import _diverse_order, _effective_query, _image_capability, _safe_error


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
