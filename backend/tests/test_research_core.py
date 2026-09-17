from collections import Counter

from app.models import Result
from app.research import _visual_match, make_queries, overlap_score
from app.worker import _diverse_order


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


def test_visual_hash_exact_match_scores_maximum() -> None:
    score, distance = _visual_match(["0000000000000000"], "0000000000000000")
    assert distance == 0
    assert score == 100.0


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
