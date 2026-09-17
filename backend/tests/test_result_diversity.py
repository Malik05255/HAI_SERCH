from app.models import Result
from app.worker import _annotate_supporting_sources, _diverse_order, _same_work_title


def _result(title: str, url: str, score: float = 80.0) -> Result:
    return Result(
        job_id="job-1",
        title=title,
        url=url,
        summary="",
        match_score=score,
        evidence={},
    )


def test_same_work_across_sources_is_not_counted_twice() -> None:
    results = [
        _result("Inception (2010) Review", "https://example.com/inception", 95),
        _result("Inception - IMDb", "https://imdb.com/title/tt1375666", 92),
        _result("Arrival (2016)", "https://example.org/arrival", 88),
    ]

    ordered = _diverse_order(results, 3)

    assert [item.title for item in ordered] == [
        "Inception (2010) Review",
        "Arrival (2016)",
    ]


def test_arabic_noise_words_do_not_create_duplicate_slots() -> None:
    assert _same_work_title(
        "فيلم المدينة 2020 مراجعة",
        "المدينة (2020) - IMDb",
    )


def test_explicit_different_years_keep_remakes_separate() -> None:
    assert not _same_work_title("Crash (1996) - IMDb", "Crash (2004) - Wikipedia")


def test_subtitles_and_sequels_are_not_collapsed() -> None:
    assert not _same_work_title("Spider Man", "Spider Man Homecoming")
    assert not _same_work_title("Dune", "Dune Part Two")


def test_domain_limit_is_soft_but_duplicate_limit_is_hard() -> None:
    results = [
        _result("Alpha (2020)", "https://same.example/a", 95),
        _result("Beta (2021)", "https://same.example/b", 94),
        _result("Gamma (2022)", "https://same.example/c", 93),
    ]

    ordered = _diverse_order(results, 3)

    assert [item.title for item in ordered] == [
        "Alpha (2020)",
        "Beta (2021)",
        "Gamma (2022)",
    ]


def test_supporting_sources_keep_one_url_per_independent_domain() -> None:
    results = [
        _result("Inception (2010) Review", "https://a.example/inception", 95),
        _result("Inception - IMDb", "https://b.example/title/tt1375666", 93),
        _result("Inception trailer", "https://a.example/inception-trailer", 91),
    ]

    _annotate_supporting_sources(results)

    evidence = results[0].evidence
    assert evidence["supporting_source_count"] == 2
    assert evidence["supporting_sources"] == [
        {"domain": "a.example", "url": "https://a.example/inception"},
        {"domain": "b.example", "url": "https://b.example/title/tt1375666"},
    ]


def test_supporting_sources_do_not_cross_different_remake_years() -> None:
    results = [
        _result("Crash (1996)", "https://a.example/crash-1996", 95),
        _result("Crash (2004)", "https://b.example/crash-2004", 93),
    ]

    _annotate_supporting_sources(results)

    assert results[0].evidence["supporting_source_count"] == 1
    assert results[1].evidence["supporting_source_count"] == 1
