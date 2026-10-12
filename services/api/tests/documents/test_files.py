"""File types, text extraction (PDF, plain text) and malformed input: no database."""

import io

import pytest
from pypdf import PdfWriter

from app.documents.extract import (
    PART_TARGET_CHARS,
    ExtractionFailed,
    clean_text,
    extract_pdf,
    extract_plain,
    extract_text_file,
    single_page_pdf,
    split_into_parts,
    strip_page_furniture,
)
from app.documents.sniff import UnsupportedFile, decode_text, detect, safe_file_name
from support.pdfs import make_pdf

LIMITS = {"max_pages": 50, "max_chars": 100_000}


# --- What a file is ---------------------------------------------------------------------------


def test_a_pdf_is_recognised_by_its_signature() -> None:
    detected = detect(make_pdf(["Hello"]), "notes.pdf")

    assert (detected.kind, detected.mime_type) == ("pdf", "application/pdf")


def test_a_pdf_with_a_little_junk_before_its_header_is_still_a_pdf() -> None:
    assert detect(b"junk\n" + make_pdf(["Hello"]), "a.pdf").kind == "pdf"


@pytest.mark.parametrize(
    ("data", "name", "mime"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"rest", "scan.png", "image/png"),
        (b"\xff\xd8\xff\xe0" + b"jfif", "photo.jpg", "image/jpeg"),
        (b"\xff\xd8\xff\xe0" + b"jfif", "photo.JPEG", "image/jpeg"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "note.webp", "image/webp"),
    ],
)
def test_images_are_recognised_by_their_signature(data: bytes, name: str, mime: str) -> None:
    detected = detect(data, name)

    assert (detected.kind, detected.mime_type) == ("image", mime)


@pytest.mark.parametrize("name", ["notes.txt", "notes.md", "README", "Notes.TXT"])
def test_plain_text_is_recognised(name: str) -> None:
    assert detect(b"Ownership means one owner.\n", name).kind == "text"


def test_text_in_utf8_with_a_bom_and_in_utf16_is_accepted() -> None:
    assert detect("\ufeffhello world".encode("utf-8"), "a.txt").kind == "text"
    assert detect("hello world".encode("utf-16"), "a.txt").kind == "text"


def test_text_in_hindi_is_accepted() -> None:
    assert detect("स्वामित्व का अर्थ है एक मालिक।".encode(), "hindi.txt").kind == "text"


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"MZ\x90\x00\x03" + b"\x00" * 40, "setup.exe"),
        (b"\x7fELF\x02\x01\x01" + b"\x00" * 40, "tool"),
        (b"PK\x03\x04" + b"\x00" * 40, "archive.zip"),
        (b"PK\x03\x04" + b"\x00" * 40, "essay.docx"),
        (bytes(range(256)) * 4, "blob.txt"),
        ("caf\xe9 cr\xe8me".encode("latin-1"), "latin.txt"),
        (b"   \n\t  ", "blank.txt"),
    ],
)
def test_anything_else_is_refused_rather_than_guessed_at(data: bytes, name: str) -> None:
    with pytest.raises(UnsupportedFile) as caught:
        detect(data, name)

    assert caught.value.code == "FILE_TYPE_UNSUPPORTED"
    assert "PDF" in caught.value.message  # it says what would be accepted


def test_an_empty_file_is_refused_with_its_own_reason() -> None:
    with pytest.raises(UnsupportedFile) as caught:
        detect(b"", "empty.txt")

    assert caught.value.code == "FILE_EMPTY"


def test_a_name_that_disagrees_with_the_content_is_refused() -> None:
    cases = [
        (make_pdf(["x"]), "notes.txt"),  # a PDF called .txt
        (b"plain text here", "notes.pdf"),  # text called .pdf
        (b"\x89PNG\r\n\x1a\nxx", "notes.pdf"),  # an image called .pdf
        (b"\x89PNG\r\n\x1a\nxx", "notes"),  # an image with no extension
        (make_pdf(["x"]), "notes"),  # a PDF with no extension
    ]
    for data, name in cases:
        with pytest.raises(UnsupportedFile) as caught:
            detect(data, name)
        assert caught.value.code == "FILE_TYPE_MISMATCH", name


def test_the_browsers_content_type_is_never_consulted() -> None:
    # detect() has no parameter for it: the type comes from the bytes alone
    assert detect(b"%PDF-1.4\n%%EOF", "a.pdf").mime_type == "application/pdf"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("My notes (final) v2.PDF", "My-notes-final-v2.pdf"),
        ("../../etc/passwd", "passwd.txt"),
        ("C:\\Users\\me\\secret.txt", "secret.txt"),
        (".env", "env.txt"),
        ("", "document.txt"),
        ("a" * 200 + ".md", "a" * 60 + ".md"),
        ("naïve notes.txt", "na-ve-notes.txt"),
        ("<script>.txt", "script.txt"),
        ("notes.tar.gz", "notes-tar.gz"),
    ],
)
def test_a_file_name_is_made_safe_for_a_storage_path(given: str, expected: str) -> None:
    safe = safe_file_name(given, "txt")

    assert safe == expected
    assert "/" not in safe and "\\" not in safe and not safe.startswith(".")


def test_decoding_does_not_guess() -> None:
    assert decode_text("héllo".encode()) == "héllo"
    assert decode_text("héllo".encode("latin-1")) is None


# --- Plain text -------------------------------------------------------------------------------


def test_text_is_cleaned_of_control_characters_and_ragged_whitespace() -> None:
    cleaned = clean_text("Line one  \r\nLine\x00 two\x07\r\n\r\n\r\n\r\nLine three\u00a0here  ")

    assert cleaned == "Line one\nLine two\n\nLine three here"


def test_short_text_is_one_part_and_long_text_is_cut_at_paragraphs() -> None:
    short = extract_plain("One paragraph only.", max_chars=10_000)
    paragraph = "This sentence is about ownership in Rust. " * 12  # about 500 characters
    long = extract_plain("\n\n".join([paragraph] * 40), max_chars=100_000)

    assert [p.number for p in short.pages] == [1] and short.paginated is False
    assert len(long.pages) > 3
    assert [p.number for p in long.pages] == list(range(1, len(long.pages) + 1))
    assert all(len(p.text) <= PART_TARGET_CHARS + 50 for p in long.pages)
    assert all(p.source == "text" for p in long.pages)


def test_every_word_of_the_text_survives_being_split_into_parts() -> None:
    sentences = [f"Fact number {i} about borrowing and ownership." for i in range(300)]
    text = "\n\n".join(" ".join(sentences[i : i + 6]) for i in range(0, 300, 6))

    parts = split_into_parts(text)

    assert " ".join(" ".join(parts).split()) == " ".join(text.split())


def test_a_single_enormous_paragraph_is_still_cut() -> None:
    parts = split_into_parts("word " * 5000)

    assert len(parts) > 3 and all(len(part) <= PART_TARGET_CHARS for part in parts)


def test_text_with_nothing_in_it_fails_clearly() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_plain(" \n\t\x00 ", max_chars=1000)

    assert caught.value.code == "DOCUMENT_EMPTY"


def test_text_longer_than_the_limit_is_refused_with_the_limit_named() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_plain("word " * 500, max_chars=1000)

    assert caught.value.code == "DOCUMENT_TOO_LARGE" and "1,000" in caught.value.message


def test_a_text_file_must_decode() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_text_file("café".encode("latin-1"), max_chars=1000)

    assert caught.value.code == "FILE_TYPE_UNSUPPORTED"
    assert (
        extract_text_file("café au lait".encode(), max_chars=1000).pages[0].text == "café au lait"
    )


# --- PDFs -------------------------------------------------------------------------------------


def test_the_text_of_each_page_is_extracted_with_its_page_number() -> None:
    pdf = make_pdf(
        ["Ownership\nEvery value has one owner.", "Borrowing rules\nA reference lets you look."]
    )

    result = extract_pdf(pdf, **LIMITS)

    assert result.paginated is True and result.page_count == 2
    assert [p.number for p in result.pages] == [1, 2]
    assert "Every value has one owner." in result.pages[0].text
    assert "A reference lets you look." in result.pages[1].text
    assert all(p.source == "text_layer" and not p.needs_ocr for p in result.pages)
    assert result.warnings == []


def test_text_with_brackets_and_backslashes_survives() -> None:
    result = extract_pdf(make_pdf(["f(x) = (a + b) \\ c"]), **LIMITS)

    assert "f(x) = (a + b)" in result.pages[0].text


def test_a_page_without_a_text_layer_is_flagged_for_ocr_and_warned_about() -> None:
    result = extract_pdf(
        make_pdf(["First page has text on it.", None, "Third page too, with text."]), **LIMITS
    )

    assert [p.needs_ocr for p in result.pages] == [False, True, False]
    assert [w.code for w in result.warnings] == ["PAGES_WITHOUT_TEXT"]
    assert result.warnings[0].page == 2 and "Page 2 has no text layer" in result.warnings[0].message


def test_a_pdf_with_no_text_at_all_is_a_scan_and_every_page_wants_ocr() -> None:
    result = extract_pdf(make_pdf([None, None]), **LIMITS)

    assert all(p.needs_ocr for p in result.pages) and result.page_count == 2


def test_a_pdf_with_too_many_pages_is_refused_naming_the_limit() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_pdf(make_pdf(["page"] * 6), max_pages=5, max_chars=100_000)

    assert caught.value.code == "PDF_TOO_LONG" and "limit is 5" in caught.value.message


def test_a_pdf_with_too_much_text_is_refused() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_pdf(make_pdf(["word " * 100] * 5), max_pages=50, max_chars=300)

    assert caught.value.code == "DOCUMENT_TOO_LARGE"


def test_a_password_protected_pdf_is_refused_with_a_hint() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(ExtractionFailed) as caught:
        extract_pdf(buffer.getvalue(), **LIMITS)

    assert caught.value.code == "PDF_ENCRYPTED" and "password" in caught.value.message


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.4\nthis is not really a pdf at all",
        b"%PDF-",
        make_pdf(["Some text on a page that will be cut off"])[:200],
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF",
        b"%PDF-1.7\n" + b"\x00\xff" * 500,
    ],
)
def test_a_damaged_pdf_fails_with_a_clear_reason_and_never_crashes(data: bytes) -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_pdf(data, **LIMITS)

    assert caught.value.code in {"DOCUMENT_UNREADABLE", "DOCUMENT_EMPTY"}
    assert caught.value.message and not caught.value.retryable


def test_a_failure_message_never_contains_the_file_s_content_or_a_traceback() -> None:
    with pytest.raises(ExtractionFailed) as caught:
        extract_pdf(b"%PDF-1.4\nSECRET-CANARY-5521 and then nonsense", **LIMITS)

    assert "SECRET-CANARY" not in caught.value.message and "Traceback" not in caught.value.message


def test_a_single_page_can_be_cut_out_as_a_pdf_of_its_own() -> None:
    pdf = make_pdf(["Page one text here.", None, "Page three text here."])

    third = single_page_pdf(pdf, 3)

    result = extract_pdf(third, **LIMITS)
    assert result.page_count == 1 and "Page three text here." in result.pages[0].text
    assert detect(third, "page.pdf").kind == "pdf"


def test_cutting_out_a_page_that_does_not_exist_fails_cleanly() -> None:
    with pytest.raises(ExtractionFailed):
        single_page_pdf(make_pdf(["only page"]), 5)


# --- Running headers and footers, symbol-font bullets -----------------------------------------


def lecture_pages(count: int = 8) -> list[str]:
    """Pages with a running header, a footer whose page number changes, and their own content."""
    return [
        f"KIIT POLYTECHNIC\nChapter {(n + 1) // 2}\nFirst line of the body.\n"
        "Second line of the body.\n"
        f"This page explains idea number {n} in a few sentences.\nFourth line of the body.\n"
        "Fifth line of the body.\nSixth line of the body.\n"
        f"Database Management System {n + 17} Swagatika Dalai"
        for n in range(1, count + 1)
    ]


def test_a_running_header_and_footer_are_not_part_of_the_content() -> None:
    cleaned = strip_page_furniture([clean_text(page) for page in lecture_pages()])

    for number, text in enumerate(cleaned, start=1):
        assert "KIIT POLYTECHNIC" not in text and "Swagatika" not in text
        assert f"Chapter {(number + 1) // 2}" in text and f"idea number {number}" in text


def test_a_footer_is_recognised_whatever_its_page_number() -> None:
    pages = [
        clean_text(
            "Top line.\nSecond line.\nThird line.\n"
            f"Body of page {n}.\nMore body text {n}.\n"
            f"Fifth line.\nSixth line.\nSeventh line.\nPage {n} of 9"
        )
        for n in range(9)
    ]

    cleaned = strip_page_furniture(pages)

    assert all("of 9" not in text for text in cleaned)
    assert all("Body of page" in text and "More body text" in text for text in cleaned)


def test_lines_that_only_look_like_headers_on_a_few_pages_are_kept() -> None:
    pages = lecture_pages(10)
    pages[3] = "A one-off line at the top\n" + pages[3]

    cleaned = strip_page_furniture([clean_text(page) for page in pages])

    assert "A one-off line at the top" in cleaned[3]


def test_a_short_document_is_left_alone() -> None:
    pages = [clean_text(page) for page in lecture_pages(3)]

    assert strip_page_furniture(pages) == pages


def test_text_in_the_middle_of_a_page_is_never_removed_even_if_it_repeats() -> None:
    middle = "Refrain line that repeats in the middle of every page"
    pages = [
        clean_text(
            f"Top {n}\nline a {n}\nline b {n}\nline c {n}\n{middle}\n"
            f"line d {n}\nline e {n}\nline f {n}\nline g {n}\nBottom {n}"
        )
        for n in range(8)
    ]

    cleaned = strip_page_furniture(pages)

    assert all(middle in text for text in cleaned)


def test_symbol_font_bullets_become_bullets_and_other_private_use_characters_vanish() -> None:
    cleaned = clean_text(" First point\n Second point\n leads to\nodd markhere")

    assert cleaned == "• First point\n• Second point\n→ leads to\nodd mark here"


def test_a_pdf_with_a_running_header_is_extracted_without_it() -> None:
    pdf = make_pdf(
        [
            f"KIIT POLYTECHNIC\nChapter {(n + 1) // 2} covers topic {n} in detail.\nFooter {n}"
            for n in range(1, 7)
        ]
    )

    extraction = extract_pdf(pdf, **LIMITS)

    assert all("KIIT" not in page.text for page in extraction.pages)
    assert "Chapter 2 covers topic 3 in detail." in extraction.pages[2].text
    assert all("Footer" not in page.text for page in extraction.pages)


def test_a_repeating_line_whose_numbers_wander_is_content_not_furniture() -> None:
    # "Question 3" is at the top of five of the eight pages, but its number is not the page's.
    numbers = [3, 1, 4, 1, 5, 9, 2, 6]
    pages = [
        clean_text(f"Question {numbers[n]}\nBody text of page {n}.\nMore text {n}.")
        for n in range(8)
    ]

    cleaned = strip_page_furniture(pages)

    assert all(f"Question {numbers[n]}" in cleaned[n] for n in range(8))
