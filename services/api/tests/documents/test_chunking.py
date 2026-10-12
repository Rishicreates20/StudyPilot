"""Cutting pages into passages: coverage, size, place, headings and overlap."""

import re
from itertools import pairwise

import pytest

from app.documents.chunking import (
    MIN_TAIL_CHARS,
    Chunk,
    chunk_pages,
    embedding_input,
    is_heading,
)

TARGET = 600
OVERLAP = 100


def words_of(text: str) -> list[str]:
    return re.findall(r"\w+", text)


def sentences(prefix: str, count: int) -> str:
    return " ".join(
        f"{prefix} sentence {i} says something specific about borrowing and ownership."
        for i in range(count)
    )


def long_document() -> list[tuple[int, str]]:
    return [
        (
            page,
            f"CHAPTER {page}\n\n{sentences(f'Page{page}a', 6)}\n\n"
            f"{page}.1 Rules\n\n{sentences(f'Page{page}b', 8)}\n\n{sentences(f'Page{page}c', 5)}",
        )
        for page in range(1, 6)
    ]


def make(pages: list[tuple[int, str]]) -> list[Chunk]:
    return chunk_pages(pages, target=TARGET, overlap=OVERLAP)


def test_a_short_document_is_one_passage_with_its_page() -> None:
    chunks = make([(3, "A short note about ownership. It fits in one passage easily enough.")])

    assert len(chunks) == 1
    assert (chunks[0].index, chunks[0].page_start, chunks[0].page_end) == (0, 3, 3)


def test_no_text_means_no_passages() -> None:
    assert make([]) == []
    assert make([(1, ""), (2, "  \n\n ")]) == []


def test_every_word_of_every_page_is_in_some_passage() -> None:
    pages = long_document()

    chunks = make(pages)

    covered = set(words_of(" ".join(c.text for c in chunks)))
    assert set(words_of(" ".join(text for _, text in pages))) <= covered


def test_passages_stay_near_the_target_size() -> None:
    chunks = make(long_document())

    assert len(chunks) > 5
    assert all(len(c.text) <= TARGET + OVERLAP + 120 for c in chunks), [len(c.text) for c in chunks]


def test_indexes_are_sequential_and_pages_never_go_backwards() -> None:
    chunks = make(long_document())

    assert [c.index for c in chunks] == list(range(len(chunks)))
    starts = [c.page_start for c in chunks]
    assert starts == sorted(starts)
    assert all(c.page_start <= c.page_end for c in chunks)


def test_a_passage_that_spans_pages_says_so() -> None:
    chunks = make(
        [(1, "First page ends with an idea about ownership."), (2, "Second page continues it.")]
    )

    assert len(chunks) == 1 and (chunks[0].page_start, chunks[0].page_end) == (1, 2)


def test_each_passage_is_found_on_the_pages_it_claims() -> None:
    pages = long_document()
    by_page = dict(pages)

    for chunk in make(pages):
        marker = re.search(r"Page(\d)[abc] sentence", chunk.text)
        if marker:
            page = int(marker.group(1))
            assert chunk.page_start <= page <= chunk.page_end, chunk.text[:80]
            assert by_page[page]


def test_the_heading_in_effect_is_kept_with_each_passage() -> None:
    pages = [
        (1, "CHAPTER ONE\n\n" + sentences("alpha", 12)),
        (2, "2.1 Borrowing rules\n\n" + sentences("beta", 12)),
    ]

    chunks = make(pages)

    assert chunks[0].section_title == "CHAPTER ONE"
    beta = [c for c in chunks if "beta sentence" in c.text]
    assert beta and beta[0].section_title in {"2.1 Borrowing rules", "CHAPTER ONE"}
    assert any(c.section_title == "2.1 Borrowing rules" for c in chunks)


def test_a_heading_goes_with_the_text_it_introduces_not_at_the_end_of_a_passage() -> None:
    fill = sentences("fill", 7)  # almost fills a passage
    pages = [(1, f"{fill}\n\nBorrowing rules\n\n{sentences('after', 5)}")]

    chunks = make(pages)

    assert len(chunks) >= 2
    assert not any(c.text.rstrip().endswith("Borrowing rules") for c in chunks)
    assert any(
        c.text.lstrip().startswith("Borrowing rules") or "\n\nBorrowing rules\n\n" in c.text
        for c in chunks
    )


def test_consecutive_passages_overlap_so_a_split_idea_is_whole_somewhere() -> None:
    chunks = make([(1, sentences("only", 40))])

    assert len(chunks) > 3
    for before, after in pairwise(chunks):
        tail_words = words_of(before.text)[-6:]
        assert " ".join(tail_words) in " ".join(words_of(after.text)), (before.index, tail_words)


def test_a_paragraph_longer_than_a_passage_is_cut_at_sentence_ends() -> None:
    chunks = make([(1, sentences("huge", 60))])

    assert len(chunks) > 3
    for chunk in chunks:
        body = chunk.text
        assert body.rstrip().endswith("ownership."), body[-60:]


def test_text_without_any_spaces_is_still_cut_to_size() -> None:
    chunks = make([(1, "x" * 5000)])

    assert len(chunks) >= 8 and all(len(c.text) <= TARGET + OVERLAP + 5 for c in chunks)


def test_a_tiny_last_passage_is_folded_into_the_one_before() -> None:
    chunks = make([(1, sentences("body", 11) + "\n\nThe end.")])

    assert all(len(c.text) >= MIN_TAIL_CHARS for c in chunks)
    assert chunks[-1].text.rstrip().endswith("The end.")


def test_the_same_pages_always_give_the_same_passages() -> None:
    pages = long_document()

    assert make(pages) == make(pages)


def test_hindi_text_is_split_at_its_sentence_marks() -> None:
    danda = "स्वामित्व का अर्थ है कि हर मान का एक ही मालिक होता है। " * 40
    chunks = make([(1, danda)])

    assert len(chunks) > 3 and all(c.text.rstrip().endswith("।") for c in chunks)


@pytest.mark.parametrize(
    ("line", "standalone", "expected"),
    [
        ("# Borrowing", False, "Borrowing"),
        ("2.1 Borrowing rules", False, "2.1 Borrowing rules"),
        ("3) Lifetimes", False, "3) Lifetimes"),
        ("OWNERSHIP AND BORROWING", False, "OWNERSHIP AND BORROWING"),
        ("Borrowing rules", True, "Borrowing rules"),
        ("Borrowing rules", False, None),
        ("This is an ordinary sentence about rust.", True, None),
        ("A question about borrowing?", True, None),
        ("a" * 120, True, None),
        ("2 owners hold the value", False, None),
        ("", True, None),
        ("....", True, None),
    ],
)
def test_headings_are_told_apart_from_sentences(
    line: str, standalone: bool, expected: str | None
) -> None:
    assert is_heading(line, standalone=standalone) == expected


def test_what_is_embedded_carries_the_document_title_and_heading() -> None:
    chunk = Chunk(index=0, page_start=1, page_end=1, section_title="Borrowing", text="A reference.")

    assert embedding_input("Rust notes", chunk) == "Rust notes\nBorrowing\nA reference."
    assert embedding_input("Rust notes", Chunk(1, 1, 1, None, "Text.")) == "Rust notes\nText."
    assert len(embedding_input("T", Chunk(2, 1, 1, None, "x" * 20_000))) <= 6000


def test_a_numbered_list_item_with_a_sentence_is_not_a_heading() -> None:
    assert (
        is_heading("1. Reduction of redundancy & inconsistency: Unlike file processing systems")
        is None
    )
    assert is_heading("2) Data is shared by many users, so one copy must stay consistent.") is None


def test_short_numbered_titles_are_still_headings() -> None:
    assert is_heading("2.1 Integrity constraints") == "2.1 Integrity constraints"
    assert is_heading("3. Normal forms") == "3. Normal forms"
