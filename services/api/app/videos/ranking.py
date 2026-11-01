"""Choosing which found videos to suggest for a topic, by explicit rules (pure: no I/O).

The score is a **match estimate from YouTube's metadata**, 0 to 100, not a judgement of quality.
Each part is recorded in ``score_basis`` so the number can be explained:

=================  ===  =========================================================================
title              35   share of the topic's words that appear in the video title
description        10   share of the topic's words that appear in the description
length             15   4 to 30 minutes is full marks; shorter or much longer gets less
category           10   YouTube's Education or Science & Technology (Howto & Style gets 6)
language           10   the video declares the language searched for (unknown gets 5)
views              10   how often it was watched, on a log scale (10 million is full marks)
search_rank        10   where YouTube itself placed it in the results
=================  ===  =========================================================================

A video is left out altogether when it is not public and processed, is live or scheduled, is
shorter than a minute (a Short) or longer than four hours, or shares no word with the topic.
"""

import math
import re
from collections.abc import Iterable

from app.videos.model import RankedVideo, VideoDetails

MIN_SECONDS = 60
MAX_SECONDS = 4 * 60 * 60
MIN_SCORE = 30
MAX_QUERY_CHARS = 100

# Spaces and punctuation, including en and em dashes and curly quotes (written as escapes).
_SPLIT = re.compile(
    "[\\s\\-\\u2013\\u2014:;,.!?()\\[\\]{}\"'\\u201c\\u201d\\u2018\\u2019/\\\\|&+#@*_<>=~`^%$]+"
)


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Words that say nothing about the subject. A topic made only of these keeps them (see ``terms``).
_STOPWORDS = _words(
    "a an the and or of to in on for with by from at as is are be been being it its this that "
    "these those how what why when which who your you our we vs via into about over under "
    "using use part chapter lesson introduction intro basics basic overview"
)
# Lead-in words of a goal's title that are not its subject ("Learn Kubernetes" -> "Kubernetes").
_GOAL_FILLER = _words(
    "learn learning master mastering study studying understand understanding improve get better "
    "become prepare preparing practice practise revise revision my i want to be able the a an "
    "for in at of and how course exam"
)
_GOOD_CATEGORIES = {"27": 10, "28": 10, "26": 6}  # Education, Science & Technology, Howto & Style


def terms(text: str) -> list[str]:
    """The meaningful words of ``text``, lower-cased, in order, each once.

    Splitting is on spaces and punctuation only, so words of scripts written with combining marks
    (Devanagari, Odia) stay whole. If every word is a stopword, the words are kept as they are.
    """
    words = [w for w in _SPLIT.split(text.casefold()) if w]
    meaningful = [w for w in words if w not in _STOPWORDS and (len(w) > 1 or w.isdigit())]
    return list(dict.fromkeys(meaningful or words))


def search_query(topic_title: str, goal_title: str) -> str:
    """What to type into YouTube for a topic: its title, then the subject words of its goal.

    Topics rarely repeat their subject ("Pods and deployments" in "Learn Kubernetes"), and without
    it a search drifts to other fields that use the same words.
    """
    topic = " ".join(topic_title.split())
    known = set(terms(topic))
    extra = [
        w for w in terms(goal_title) if w not in known and w not in _GOAL_FILLER and not w.isdigit()
    ]
    query = topic
    for word in extra:
        if len(query) + 1 + len(word) > MAX_QUERY_CHARS:
            break
        query = f"{query} {word}"
    return query[:MAX_QUERY_CHARS].strip()


def search_languages(roadmap_language: str) -> tuple[str, ...]:
    """The languages to search, in order: the roadmap's, then English when it is another one."""
    base = roadmap_language.split("-")[0].strip().casefold()
    if not re.fullmatch(r"[a-z]{2,3}", base):
        base = "en"
    return (base,) if base == "en" else (base, "en")


def exclusion(video: VideoDetails, topic_terms: Iterable[str]) -> str | None:
    """Why ``video`` must not be suggested, or None if it may be."""
    if not video.watchable:
        return "not_public"
    if video.live:
        return "live"
    if video.duration_seconds is None:
        return "no_length"
    if video.duration_seconds < MIN_SECONDS:
        return "too_short"
    if video.duration_seconds > MAX_SECONDS:
        return "too_long"
    words = set(terms(f"{video.title} {video.description}"))
    if not words & set(topic_terms):
        return "off_topic"
    return None


def score(
    video: VideoDetails,
    *,
    topic_terms: list[str],
    searched_language: str,
    search_rank: int,
    result_count: int,
) -> tuple[int, dict[str, int]]:
    """The match estimate (0..100) and its parts."""
    wanted = set(topic_terms)
    title_words = set(terms(video.title))
    description_words = set(terms(video.description))
    share_title = len(wanted & title_words) / len(wanted) if wanted else 0.0
    share_description = len(wanted & description_words) / len(wanted) if wanted else 0.0
    basis = {
        "title": round(35 * share_title),
        "description": round(10 * share_description),
        "length": _length_points(video.duration_seconds),
        "category": _GOOD_CATEGORIES.get(video.category_id or "", 0),
        "language": _language_points(video.language, searched_language),
        "views": _view_points(video.view_count),
        "search_rank": _rank_points(search_rank, result_count),
    }
    return max(0, min(100, sum(basis.values()))), basis


def rank_videos(
    found: Iterable[tuple[VideoDetails, str, int, int]],
    *,
    topic_title: str,
    limit: int,
) -> list[RankedVideo]:
    """The videos worth suggesting, best first, at most ``limit``.

    ``found`` holds (details, searched language, YouTube's rank, size of that result list). Ties
    keep YouTube's own order. At most two videos of one channel are kept, so one channel's series
    does not fill the list.
    """
    topic_terms = terms(topic_title)
    candidates: list[tuple[int, int, VideoDetails, str, dict[str, int]]] = []
    seen: set[str] = set()
    for video, language, rank, total in found:
        if video.video_id in seen or exclusion(video, topic_terms) is not None:
            continue
        seen.add(video.video_id)
        value, basis = score(
            video,
            topic_terms=topic_terms,
            searched_language=language,
            search_rank=rank,
            result_count=total,
        )
        if value >= MIN_SCORE:
            candidates.append((value, rank, video, language, basis))
    candidates.sort(key=lambda entry: (-entry[0], entry[1]))

    kept: list[RankedVideo] = []
    per_channel: dict[str, int] = {}
    for value, _rank, video, language, basis in candidates:
        channel = video.channel_id or video.channel_title
        if channel and per_channel.get(channel, 0) >= 2:
            continue
        per_channel[channel] = per_channel.get(channel, 0) + 1
        kept.append(
            RankedVideo(
                details=video,
                searched_language=language,
                relevance_score=value,
                score_basis=basis,
                position=len(kept) + 1,
            )
        )
        if len(kept) >= limit:
            break
    return kept


def _length_points(seconds: int | None) -> int:
    if seconds is None:
        return 0
    minutes = seconds / 60
    if 4 <= minutes <= 30:
        return 15
    if 2 <= minutes < 4 or 30 < minutes <= 60:
        return 10
    if 60 < minutes <= 120:
        return 5
    return 0


def _language_points(declared: str | None, searched: str) -> int:
    if declared is None:
        return 5
    return 10 if declared.split("-")[0].casefold() == searched.casefold() else 0


def _view_points(views: int | None) -> int:
    if not views:
        return 0
    return min(10, round(math.log10(views + 1) * 10 / 7))


def _rank_points(rank: int, total: int) -> int:
    if total <= 0 or rank < 1:
        return 0
    return max(0, round(10 * (1 - (rank - 1) / total)))
