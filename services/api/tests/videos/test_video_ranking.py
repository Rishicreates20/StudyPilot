"""The rules that choose which found videos to suggest (pure: no network, no database)."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.videos.model import VideoDetails, watch_url
from app.videos.quota import quota_day
from app.videos.ranking import (
    MIN_SCORE,
    exclusion,
    rank_videos,
    score,
    search_languages,
    search_query,
    terms,
)
from app.videos.youtube import parse_duration

TOPIC = "Ownership and borrowing"


def video(video_id: str = "aaaaaaaaaaa", **fields: object) -> VideoDetails:
    values: dict[str, object] = {
        "video_id": video_id,
        "title": "Rust ownership and borrowing explained",
        "description": "How ownership works in Rust, with examples.",
        "channel_id": "UC-one",
        "channel_title": "One",
        "published_at": None,
        "duration_seconds": 12 * 60,
        "category_id": "27",
        "language": "en",
        "language_source": "audio",
        "thumbnail_url": None,
        "thumbnail_width": None,
        "thumbnail_height": None,
        "view_count": 250_000,
        "watchable": True,
        "live": False,
    }
    values.update(fields)
    return VideoDetails(**values)  # type: ignore[arg-type]


# --- Words and queries -------------------------------------------------------------------------


def test_terms_drop_stopwords_and_punctuation_and_keep_order() -> None:
    dash, left, right = chr(0x2013), chr(0x201C), chr(0x201D)  # an en dash and curly quotes
    assert terms(f"Ownership {dash} and {left}borrowing{right}: the basics") == [
        "ownership",
        "borrowing",
    ]


def test_terms_keep_words_written_with_combining_marks_whole() -> None:
    # Devanagari vowel signs are combining marks; splitting on \W would cut the words apart.
    assert terms("गति के नियम") == [
        "गति",
        "के",
        "नियम",
    ]


def test_a_title_made_only_of_stopwords_keeps_its_words() -> None:
    assert terms("How to use it") == ["how", "to", "use", "it"]


def test_the_query_adds_the_goals_subject_but_not_its_filler() -> None:
    assert search_query("Pods and deployments", "Learn Kubernetes") == (
        "Pods and deployments kubernetes"
    )


def test_the_query_does_not_repeat_words_the_topic_already_has() -> None:
    assert search_query("Kubernetes pods", "Learn Kubernetes") == "Kubernetes pods"


def test_the_query_is_capped() -> None:
    query = search_query("A" * 95, "Learn " + " ".join(f"word{n}" for n in range(30)))
    assert len(query) <= 100


@pytest.mark.parametrize(
    ("roadmap_language", "expected"),
    [
        ("en", ("en",)),
        ("en-GB", ("en",)),
        ("hi", ("hi", "en")),
        ("or", ("or", "en")),
        ("", ("en",)),
    ],
)
def test_the_roadmaps_language_is_searched_first_then_english(
    roadmap_language: str, expected: tuple[str, ...]
) -> None:
    assert search_languages(roadmap_language) == expected


# --- Lengths, links and the quota day ----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("PT12M30S", 750),
        ("PT1H", 3600),
        ("PT45S", 45),
        ("P1DT2H", 93_600),
        ("PT0S", None),  # what live streams report
        ("P0D", None),
        ("12:30", None),
        (None, None),
    ],
)
def test_iso_durations_are_read_as_seconds(value: object, seconds: int | None) -> None:
    assert parse_duration(value) == seconds


def test_a_link_is_only_ever_the_watch_address_of_a_real_id() -> None:
    assert watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    for bad in ("short", "dQw4w9WgXcQ&list=x", "../../evil1", "javascript:"):
        with pytest.raises(ValueError, match="not a YouTube video id"):
            watch_url(bad)


def test_the_quota_day_is_the_pacific_date() -> None:
    # 07:00 UTC is still the previous evening in California (UTC-8 in winter).
    assert quota_day(datetime(2026, 1, 15, 7, 0, tzinfo=UTC)).isoformat() == "2026-01-14"
    assert quota_day(datetime(2026, 1, 15, 9, 0, tzinfo=UTC)).isoformat() == "2026-01-15"


# --- What is left out --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"watchable": False}, "not_public"),
        ({"live": True}, "live"),
        ({"duration_seconds": None}, "no_length"),
        ({"duration_seconds": 45}, "too_short"),
        ({"duration_seconds": 5 * 3600}, "too_long"),
        ({"title": "Cooking pasta at home", "description": "Dinner ideas"}, "off_topic"),
    ],
)
def test_unsuitable_videos_are_left_out(change: dict[str, object], reason: str) -> None:
    assert exclusion(replace(video(), **change), terms(TOPIC)) == reason  # type: ignore[arg-type]


def test_a_suitable_video_is_kept() -> None:
    assert exclusion(video(), terms(TOPIC)) is None


# --- The score -----------------------------------------------------------------------------------


def test_the_score_is_explained_by_its_parts() -> None:
    value, basis = score(
        video(), topic_terms=terms(TOPIC), searched_language="en", search_rank=1, result_count=10
    )

    assert set(basis) == {
        "title",
        "description",
        "length",
        "category",
        "language",
        "views",
        "search_rank",
    }
    assert value == sum(basis.values())
    assert basis["title"] == 35  # both topic words are in the title
    assert basis["description"] == 5  # one of the two is in the description
    assert (basis["length"], basis["category"], basis["language"]) == (15, 10, 10)
    assert basis["search_rank"] == 10


def test_a_video_in_another_language_than_searched_loses_the_language_points() -> None:
    _, basis = score(
        video(language="de"),
        topic_terms=terms(TOPIC),
        searched_language="en",
        search_rank=1,
        result_count=10,
    )
    assert basis["language"] == 0


def test_an_undeclared_language_gets_half_the_language_points() -> None:
    _, basis = score(
        video(language=None, language_source="unknown"),
        topic_terms=terms(TOPIC),
        searched_language="en",
        search_rank=1,
        result_count=10,
    )
    assert basis["language"] == 5


def test_the_score_never_leaves_0_to_100() -> None:
    best, _ = score(
        video(view_count=10**12),
        topic_terms=terms(TOPIC),
        searched_language="en",
        search_rank=1,
        result_count=1,
    )
    assert 0 <= best <= 100


# --- Ranking -------------------------------------------------------------------------------------


def test_videos_are_ranked_best_first_and_numbered() -> None:
    weak = video("weakweak001", title="Borrowing money tips", description="", category_id="22")
    strong = video("strongvid01")
    ranked = rank_videos([(weak, "en", 1, 2), (strong, "en", 2, 2)], topic_title=TOPIC, limit=5)

    assert [v.details.video_id for v in ranked] == ["strongvid01", "weakweak001"]
    assert [v.position for v in ranked] == [1, 2]
    assert ranked[0].relevance_score > ranked[1].relevance_score >= MIN_SCORE


def test_ranking_keeps_at_most_the_limit_and_two_videos_per_channel() -> None:
    same_channel = [video(f"chanA{n:06d}", channel_id="UC-A") for n in range(4)]
    other = video("chanB000001", channel_id="UC-B")
    ranked = rank_videos(
        [(v, "en", n + 1, 5) for n, v in enumerate([*same_channel, other])],
        topic_title=TOPIC,
        limit=3,
    )

    assert [v.details.video_id for v in ranked] == ["chanA000000", "chanA000001", "chanB000001"]


def test_ranking_drops_duplicates_unsuitable_videos_and_low_scores() -> None:
    good = video("goodvideo01")
    short = video("shortvid001", duration_seconds=30)
    ranked = rank_videos(
        [(good, "en", 1, 3), (good, "en", 2, 3), (short, "en", 3, 3)], topic_title=TOPIC, limit=5
    )

    assert [v.details.video_id for v in ranked] == ["goodvideo01"]


def test_nothing_suitable_is_a_valid_empty_answer() -> None:
    off = video("offtopic001", title="Holiday vlog", description="Beach day")
    assert rank_videos([(off, "en", 1, 1)], topic_title=TOPIC, limit=5) == []
