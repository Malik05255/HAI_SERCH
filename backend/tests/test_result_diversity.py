from app.models import Result
from app.worker import _diverse_order, _same_work_title


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
