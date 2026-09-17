from app.models import Result
from app.research import Candidate, _evidence_summary, _has_verifiable_evidence
from app.worker import _annotate_supporting_sources, _diverse_order, _same_work_title


def _result(title: str, url: str, score: float = 90.0) -> Result:
    return Result(
        job_id="quality-job",
        title=title,
        url=url,
        summary="",
        match_score=score,
        evidence={"verified_page": True},
    )


def test_title_identity_quality_matrix() -> None:
    cases = [
        ("Inception (2010) Review", "Inception - IMDb 2010", True),
        ("The Raid (2011) Official Trailer", "The Raid 2011 - IMDb", True),
        ("فيلم المدينة 2020 مراجعة", "المدينة (2020) - IMDb", True),
        ("Crash (1996)", "Crash (2004)", False),
        ("Dune", "Dune Part Two", False),
        ("Spider Man", "Spider Man Homecoming", False),
    ]
    for left, right, expected in cases:
        assert _same_work_title(left, right) is expected


def test_unique_work_slots_never_get_padded_with_duplicate_pages() -> None:
    rows = [
        _result("Inception (2010) Review", "https://a.example/inception", 96),
        _result("Inception - IMDb 2010", "https://b.example/inception", 94),
        _result("Arrival (2016)", "https://c.example/arrival", 91),
    ]
    ordered = _diverse_order(rows, 3)
    assert [item.title for item in ordered] == [
        "Inception (2010) Review",
        "Arrival (2016)",
    ]


def test_independent_sources_are_preserved_without_inflating_result_count() -> None:
    rows = [
        _result("Inception (2010) Review", "https://a.example/inception", 96),
        _result("Inception - IMDb 2010", "https://b.example/title", 94),
        _result("Inception official trailer", "https://a.example/trailer", 88),
    ]
    _annotate_supporting_sources(rows)
    assert rows[0].evidence["supporting_source_count"] == 2


def test_evidence_summary_surfaces_clues_not_page_boilerplate() -> None:
    page = (
        "Welcome to the archive. "
        "The hero leaves the village for the city and becomes a driver. "
        "Navigation and copyright information. "
        "At the ending he does not marry the heroine and returns home."
    )
    summary = _evidence_summary(
        page,
        ["hero village city driver", "ending does not marry heroine"],
    )
    assert "leaves the village for the city" in summary
    assert "does not marry the heroine" in summary


def test_snippet_alone_is_not_a_quality_pass_but_strong_visual_match_is() -> None:
    snippet_only = Candidate(
        title="Possible result",
        url="https://example.com/item",
        image_url=None,
        snippet="matching search snippet",
        summary="",
        score=90,
    )
    assert _has_verifiable_evidence(snippet_only, "") is False

    visual = Candidate(
        title="Visual result",
        url="https://example.org/item",
        image_url="https://example.org/image.jpg",
        snippet="",
        summary="",
        score=90,
        visual_distance=2,
    )
    assert _has_verifiable_evidence(visual, "") is True
