"""Study documents through the HTTP API: uploads, review, search, deletion and who can see what."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.ai.fake import FakeProvider
from app.ai.provider import OcrResult, Usage
from app.core.rate_limit import SlidingWindowLimiter
from app.documents.storage import LocalFiles
from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status
from support.database import admin
from support.pdfs import make_pdf
from support.worker import clear_queue, run_worker_once

MakeLearner = Callable[..., Learner]

OWNERSHIP = (
    "Ownership is the rule that makes Rust memory safe without a garbage collector. "
    "Each value has exactly one owner, and the value is dropped when its owner goes out of scope."
)
BORROWING = (
    "Borrowing lets code use a value through a reference without taking ownership. "
    "A mutable reference must be unique."
)
PNG = b"\x89PNG\r\n\x1a\n" + b"not-really-an-image" * 10


def reading(text: str, legibility: Any = "clear") -> OcrResult:
    return OcrResult(
        text=text,
        legibility=legibility,
        provider="fake",
        model_id="fake-ocr-1",
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        synthetic=True,
    )


@pytest.fixture
def store(api_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFiles:
    """Uploaded files go to a temporary folder for the duration of one test."""
    files = LocalFiles(tmp_path / "files")
    monkeypatch.setattr(api_app.state, "files", files)
    monkeypatch.setattr(api_app.state, "provider", FakeProvider())
    monkeypatch.setattr(api_app.state, "search_limiter", SlidingWindowLimiter(100, 3600))
    return files


@pytest.fixture
def alice(make_learner: MakeLearner) -> Learner:
    return make_learner()


@pytest.fixture
def bob(make_learner: MakeLearner) -> Learner:
    return make_learner()


@pytest.fixture
def goal(api: TestClient, alice: Learner) -> str:
    return create_goal(api, alice)["id"]


def upload(
    api: TestClient,
    learner: Learner,
    goal_id: str,
    data: bytes,
    name: str = "notes.txt",
    **params: str,
) -> Response:
    return api.post(
        f"/v1/goals/{goal_id}/documents",
        headers={**learner.headers, "Content-Type": "application/octet-stream"},
        params={"name": name, **params},
        content=data,
    )


def paste(api: TestClient, learner: Learner, goal_id: str, **body: Any) -> Response:
    return api.post(
        f"/v1/goals/{goal_id}/documents/paste",
        headers=learner.headers,
        json={"title": "My notes", "text": OWNERSHIP, **body},
    )


def process(dsn: str, store: LocalFiles, provider: FakeProvider | None = None) -> bool:
    return run_worker_once(dsn, provider or FakeProvider(), files=store)


def add_ready(
    api: TestClient,
    dsn: str,
    store: LocalFiles,
    learner: Learner,
    goal_id: str,
    data: bytes = OWNERSHIP.encode(),
    name: str = "notes.txt",
    provider: FakeProvider | None = None,
) -> dict[str, Any]:
    """Upload a document and run its job with the real worker. Returns the document."""
    clear_queue(dsn)  # leftovers from other tests must not be picked up instead of this job
    response = upload(api, learner, goal_id, data, name)
    assert response.status_code == 202, response.text
    assert process(dsn, store, provider) is True
    return get(api, learner, response.json()["id"]).json()


def get(api: TestClient, learner: Learner, document_id: str) -> Response:
    return api.get(f"/v1/documents/{document_id}", headers=learner.headers)


def search(api: TestClient, learner: Learner, goal_id: str, query: str, **body: Any) -> Response:
    return api.post(
        f"/v1/goals/{goal_id}/documents/search",
        headers=learner.headers,
        json={"query": query, **body},
    )


# --- Adding a document ------------------------------------------------------------------------


def test_uploading_a_text_file_stores_it_privately_and_queues_processing(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str
) -> None:
    response = upload(api, alice, goal, OWNERSHIP.encode(), title="Rust notes")

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["title"], body["kind"], body["status"]) == ("Rust notes", "text", "queued")
    assert body["original_name"] == "notes.txt" and body["size_bytes"] == len(OWNERSHIP)
    assert body["job"]["job_type"] == "document" and body["job"]["document_id"] == body["id"]
    assert body["job"]["status"] == "queued"
    # What the API shows never includes where the file is kept, its hash or any signed link.
    assert not {"storage_path", "sha256", "user_id", "object", "request"} & body.keys()
    assert "object" not in str(body["job"])
    stored = list(Path(store._root).rglob("*.txt"))  # pyright: ignore[reportPrivateUsage]
    assert len(stored) == 1 and stored[0].parent.parent.name == str(alice.id)


def test_a_title_defaults_to_the_file_name(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str
) -> None:
    body = upload(api, alice, goal, OWNERSHIP.encode(), name="Chapter 3 - Ownership.md").json()

    assert body["title"] == "Chapter 3 - Ownership"


def test_processing_makes_a_document_ready_and_readable(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(
        api, database_dsn, store, alice, goal, f"{OWNERSHIP}\n\n{BORROWING}".encode()
    )

    assert document["status"] == "ready" and document["error_code"] is None
    assert document["chunk_count"] >= 1 and document["indexed_at"] is not None
    assert document["embedding_model"] == "fake-embedding-1"
    assert document["job"]["status"] == "completed"
    pages = api.get(f"/v1/documents/{document['id']}/pages", headers=alice.headers).json()
    assert pages["total"] >= 1 and pages["editable"] is False
    assert "Ownership" in pages["items"][0]["text"] and pages["items"][0]["source"] == "text"


def test_a_pdf_is_processed_page_by_page(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    pdf = make_pdf([OWNERSHIP, BORROWING])

    document = add_ready(api, database_dsn, store, alice, goal, pdf, "rust.pdf")

    assert (document["kind"], document["status"], document["paginated"]) == ("pdf", "ready", True)
    assert document["page_count"] == 2
    pages = api.get(f"/v1/documents/{document['id']}/pages", headers=alice.headers).json()
    assert [(p["page_number"], p["source"]) for p in pages["items"]] == [
        (1, "text_layer"),
        (2, "text_layer"),
    ]


def test_pasted_material_is_stored_and_processed_like_a_file(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    clear_queue(database_dsn)
    response = paste(api, alice, goal)
    assert response.status_code == 202, response.text
    assert process(database_dsn, store) is True

    document = get(api, alice, response.json()["id"]).json()
    assert (document["kind"], document["status"]) == ("pasted", "ready")
    assert document["original_name"] is None


def test_the_list_shows_documents_limits_and_what_this_server_can_do(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    add_ready(api, database_dsn, store, alice, goal)

    body = api.get(f"/v1/goals/{goal}/documents", headers=alice.headers).json()

    assert len(body["items"]) == 1 and body["items"][0]["job"]["status"] == "completed"
    assert body["limits"]["max_bytes"] == 10 * 1024 * 1024 and body["limits"]["max_ocr_pages"] == 20
    assert (body["goal_archived"], body["storage_available"]) == (False, True)
    assert body["ocr_available"] is True and body["indexing_available"] is True


# --- Refusing bad files -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "status", "code"),
    [
        (b"", "empty.txt", 422, "FILE_EMPTY"),
        (b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 200, "run.txt", 415, "FILE_TYPE_UNSUPPORTED"),
        (b"\x00\x01\x02\x03" * 100, "notes.pdf", 415, "FILE_TYPE_UNSUPPORTED"),
        (make_pdf(["A page of text for the file."]), "notes.txt", 415, "FILE_TYPE_MISMATCH"),
        (
            b"<html><script>alert(1)</script></html>\x00\x00",
            "page.html",
            415,
            "FILE_TYPE_UNSUPPORTED",
        ),
        (PNG, "photo.pdf", 415, "FILE_TYPE_MISMATCH"),
    ],
)
def test_a_file_is_judged_by_its_content_not_its_name(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str,
    data: bytes, name: str, status: int, code: str,
) -> None:  # fmt: skip
    response = upload(api, alice, goal, data, name)

    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code
    assert list(Path(store._root).rglob("*.*")) == []  # pyright: ignore[reportPrivateUsage]
    assert api.get(f"/v1/goals/{goal}/documents", headers=alice.headers).json()["items"] == []


def test_a_file_over_the_limit_is_refused_before_it_is_stored(
    api: TestClient,
    configure_app: Callable[..., None],
    store: LocalFiles,
    alice: Learner,
    goal: str,
) -> None:
    configure_app(document_max_bytes=1024)

    response = upload(api, alice, goal, b"a few words " * 200)

    assert response.status_code == 413 and response.json()["code"] == "FILE_TOO_LARGE"
    assert list(Path(store._root).rglob("*.*")) == []  # pyright: ignore[reportPrivateUsage]


def test_pasted_text_over_the_limit_is_refused(
    api: TestClient,
    configure_app: Callable[..., None],
    store: LocalFiles,
    alice: Learner,
    goal: str,
) -> None:
    configure_app(document_max_bytes=1024)

    response = paste(api, alice, goal, text="word " * 500)

    assert response.status_code == 413 and response.json()["code"] == "FILE_TOO_LARGE"


def test_the_name_is_required_and_requests_cannot_name_an_owner(
    api: TestClient, store: LocalFiles, alice: Learner, bob: Learner, goal: str
) -> None:
    missing = api.post(f"/v1/goals/{goal}/documents", headers=alice.headers, content=b"hello there")
    assert missing.status_code == 422

    smuggled = paste(api, alice, goal, user_id=str(bob.id))
    assert smuggled.status_code == 422
    assert paste(api, alice, goal, title="  ").status_code == 422
    assert paste(api, alice, goal, text="").status_code == 422


def test_the_same_file_cannot_be_added_twice_to_a_goal_but_may_go_in_another(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str
) -> None:
    assert upload(api, alice, goal, OWNERSHIP.encode()).status_code == 202

    again = upload(api, alice, goal, OWNERSHIP.encode(), "copy.txt")

    assert again.status_code == 409 and again.json()["code"] == "DOCUMENT_EXISTS"
    other_goal = create_goal(api, alice, title="Another goal")["id"]
    assert upload(api, alice, other_goal, OWNERSHIP.encode()).status_code == 202


def test_limits_on_documents_and_on_processing_per_day(
    api: TestClient,
    configure_app: Callable[..., None],
    store: LocalFiles,
    alice: Learner,
    goal: str,
) -> None:
    configure_app(documents_per_goal=1)
    assert upload(api, alice, goal, b"first document text").status_code == 202
    full = upload(api, alice, goal, b"second document text")
    assert full.status_code == 409 and full.json()["code"] == "DOCUMENT_LIMIT_REACHED"

    other_goal = create_goal(api, alice, title="Another goal")["id"]
    configure_app(document_jobs_per_user_per_day=1)
    today = upload(api, alice, other_goal, b"third document text")
    assert today.status_code == 429 and today.json()["code"] == "DOCUMENT_LIMIT_REACHED_TODAY"


def test_an_archived_goal_takes_no_new_documents(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str
) -> None:
    set_status(api, alice, goal, "archived")

    for response in (upload(api, alice, goal, OWNERSHIP.encode()), paste(api, alice, goal)):
        assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"


def test_uploads_need_storage_and_the_ai_service(
    api: TestClient,
    api_app: FastAPI,
    configure_app: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    store: LocalFiles,
    alice: Learner,
    goal: str,
) -> None:
    configure_app(llm_provider=None)
    no_ai = upload(api, alice, goal, OWNERSHIP.encode())
    assert no_ai.status_code == 503 and no_ai.json()["code"] == "AI_NOT_CONFIGURED"

    configure_app()  # back to the fake provider
    monkeypatch.setattr(api_app.state, "files", None)
    no_storage = upload(api, alice, goal, OWNERSHIP.encode())
    assert no_storage.status_code == 503 and no_storage.json()["code"] == "STORAGE_NOT_CONFIGURED"
    listed = api.get(f"/v1/goals/{goal}/documents", headers=alice.headers).json()
    assert listed["storage_available"] is False


# --- Whose documents are whose ----------------------------------------------------------------


def test_every_document_route_needs_a_valid_token(
    api: TestClient, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = upload(api, alice, goal, OWNERSHIP.encode()).json()["id"]
    routes = [
        ("get", f"/v1/goals/{goal}/documents"),
        ("post", f"/v1/goals/{goal}/documents"),
        ("post", f"/v1/goals/{goal}/documents/paste"),
        ("post", f"/v1/goals/{goal}/documents/search"),
        ("get", f"/v1/documents/{document}"),
        ("patch", f"/v1/documents/{document}"),
        ("get", f"/v1/documents/{document}/pages"),
        ("put", f"/v1/documents/{document}/pages/1"),
        ("post", f"/v1/documents/{document}/confirm"),
        ("post", f"/v1/documents/{document}/reprocess"),
        ("get", f"/v1/documents/{document}/file"),
        ("delete", f"/v1/documents/{document}"),
    ]
    for method, path in routes:
        assert api.request(method, path).status_code == 401, path
        bad = api.request(method, path, headers={"Authorization": "Bearer not.a.token"})
        assert bad.status_code == 401, path


def test_another_learners_goal_and_documents_look_like_they_do_not_exist(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, bob: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)["id"]
    h = bob.headers

    assert api.get(f"/v1/goals/{goal}/documents", headers=h).status_code == 404
    assert upload(api, bob, goal, b"bobs own text").status_code == 404
    assert paste(api, bob, goal).status_code == 404
    assert search(api, bob, goal, "ownership").status_code == 404
    for response in (
        api.get(f"/v1/documents/{document}", headers=h),
        api.patch(f"/v1/documents/{document}", headers=h, json={"title": "Mine now"}),
        api.get(f"/v1/documents/{document}/pages", headers=h),
        api.put(f"/v1/documents/{document}/pages/1", headers=h, json={"text": "overwritten"}),
        api.post(f"/v1/documents/{document}/confirm", headers=h),
        api.post(f"/v1/documents/{document}/reprocess", headers=h),
        api.get(f"/v1/documents/{document}/file", headers=h),
        api.delete(f"/v1/documents/{document}", headers=h),
        api.get(f"/v1/documents/{uuid4()}", headers=h),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["code"] in {"DOCUMENT_NOT_FOUND", "GOAL_NOT_FOUND"}
    assert get(api, alice, document).status_code == 200


# --- Review of text read from pictures --------------------------------------------------------


def test_uncertain_handwriting_waits_for_review_and_can_be_corrected_then_used(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    provider = FakeProvider(ocr=lambda image, mime: reading("Ownershp meens wun ownr", "partly"))

    document = add_ready(api, database_dsn, store, alice, goal, PNG, "notes.png", provider)

    assert (document["status"], document["needs_review"], document["ocr_page_count"]) == (
        "review", True, 1
    )  # fmt: skip
    assert document["chunk_count"] == 0 and [w["code"] for w in document["warnings"]] == [
        "OCR_UNCERTAIN"
    ]
    pages = api.get(f"/v1/documents/{document['id']}/pages", headers=alice.headers).json()
    assert pages["editable"] is True
    assert (pages["items"][0]["source"], pages["items"][0]["legibility"]) == ("ocr", "partly")
    assert pages["items"][0]["needs_review"] is True
    # Nothing is searchable until the learner has confirmed the text.
    assert search(api, alice, goal, "ownership").json()["enough_evidence"] is False

    edited = api.put(
        f"/v1/documents/{document['id']}/pages/1",
        headers=alice.headers,
        json={"text": "Ownership means one owner."},
    )
    assert edited.status_code == 200 and edited.json()["edited"] is True
    assert edited.json()["needs_review"] is False

    clear_queue(database_dsn)
    confirmed = api.post(f"/v1/documents/{document['id']}/confirm", headers=alice.headers)
    assert confirmed.status_code == 202 and confirmed.json()["status"] == "queued"
    assert process(database_dsn, store, provider) is True

    ready = get(api, alice, document["id"]).json()
    assert ready["status"] == "ready" and ready["chunk_count"] == 1
    assert len(provider.images_read) == 1  # the picture was not read again
    found = search(api, alice, goal, "Which rule says each value has one owner?").json()
    assert found["enough_evidence"] is True
    assert found["items"][0]["content"].startswith("Ownership means one owner")


def test_text_can_be_corrected_only_while_a_document_waits_for_review(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)

    response = api.put(
        f"/v1/documents/{document['id']}/pages/1", headers=alice.headers, json={"text": "changed"}
    )

    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_NOT_IN_REVIEW"
    nothing = api.post(f"/v1/documents/{document['id']}/confirm", headers=alice.headers)
    assert nothing.status_code == 409 and nothing.json()["code"] == "NOTHING_TO_CONFIRM"


def test_a_page_that_does_not_exist_cannot_be_corrected(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    provider = FakeProvider(ocr=lambda image, mime: reading("Unsure words", "poor"))
    document = add_ready(api, database_dsn, store, alice, goal, PNG, "notes.png", provider)

    missing = api.put(
        f"/v1/documents/{document['id']}/pages/9", headers=alice.headers, json={"text": "x"}
    )
    too_long = api.put(
        f"/v1/documents/{document['id']}/pages/1",
        headers=alice.headers,
        json={"text": "x" * 400_001},
    )

    assert missing.status_code == 404 and missing.json()["code"] == "PAGE_NOT_FOUND"
    assert too_long.status_code == 422


# --- Failures and processing again ------------------------------------------------------------


def test_a_damaged_pdf_fails_with_a_reason_and_can_be_processed_again(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    broken = b"%PDF-1.7\n1 0 obj << /Broken >> endobj\n" + b"\x00\x01garbage" * 50

    document = add_ready(api, database_dsn, store, alice, goal, broken, "broken.pdf")

    assert document["status"] == "failed" and document["error_code"] == "DOCUMENT_UNREADABLE"
    assert "damaged" in document["error_message"]
    assert document["job"]["status"] == "failed"
    retry = api.post(f"/v1/jobs/{document['job']['id']}/retry", headers=alice.headers)
    assert retry.status_code == 409 and retry.json()["code"] == "JOB_NOT_RETRYABLE"

    clear_queue(database_dsn)
    again = api.post(f"/v1/documents/{document['id']}/reprocess", headers=alice.headers)
    assert again.status_code == 202 and again.json()["status"] == "queued"
    assert again.json()["error_code"] is None
    assert process(database_dsn, store) is True
    assert get(api, alice, document["id"]).json()["status"] == "failed"  # still damaged


def test_processing_again_replaces_the_indexed_content(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)
    before = admin(database_dsn).fetchall(
        "select id from public.document_chunks where document_id = %s", (document["id"],)
    )

    clear_queue(database_dsn)
    response = api.post(f"/v1/documents/{document['id']}/reprocess", headers=alice.headers)
    assert response.status_code == 202, response.text
    busy = api.post(f"/v1/documents/{document['id']}/reprocess", headers=alice.headers)
    assert busy.status_code == 409 and busy.json()["code"] == "DOCUMENT_BUSY"
    assert process(database_dsn, store) is True

    after = admin(database_dsn).fetchall(
        "select id from public.document_chunks where document_id = %s", (document["id"],)
    )
    assert len(after) == len(before) > 0
    assert {r["id"] for r in after}.isdisjoint({r["id"] for r in before})
    assert get(api, alice, document["id"]).json()["status"] == "ready"


def test_a_document_cannot_be_reprocessed_or_confirmed_in_an_archived_goal(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)["id"]
    set_status(api, alice, goal, "archived")

    for response in (
        api.post(f"/v1/documents/{document}/reprocess", headers=alice.headers),
        api.post(f"/v1/documents/{document}/confirm", headers=alice.headers),
        api.patch(f"/v1/documents/{document}", headers=alice.headers, json={"title": "New"}),
        api.delete(f"/v1/documents/{document}", headers=alice.headers),
    ):
        assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"
    assert get(api, alice, document).status_code == 200  # still readable


def test_a_queued_document_job_can_be_cancelled(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    created = upload(api, alice, goal, OWNERSHIP.encode()).json()

    cancelled = api.post(f"/v1/jobs/{created['job']['id']}/cancel", headers=alice.headers)

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["document_id"] == created["id"]


# --- Renaming, downloading, deleting ----------------------------------------------------------


def test_a_document_can_be_renamed(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)

    renamed = api.patch(
        f"/v1/documents/{document['id']}", headers=alice.headers, json={"title": "Chapter 4"}
    )

    assert renamed.status_code == 200 and renamed.json()["title"] == "Chapter 4"
    blank = api.patch(f"/v1/documents/{document['id']}", headers=alice.headers, json={"title": " "})
    assert blank.status_code == 422
    owned = api.patch(
        f"/v1/documents/{document['id']}", headers=alice.headers,
        json={"title": "x", "user_id": str(alice.id)},
    )  # fmt: skip
    assert owned.status_code == 422


def test_the_original_file_downloads_as_an_attachment_never_inline(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(
        api, database_dsn, store, alice, goal, make_pdf([OWNERSHIP]), "My Notes.pdf"
    )

    response = api.get(f"/v1/documents/{document['id']}/file", headers=alice.headers)

    assert response.status_code == 200 and response.content == make_pdf([OWNERSHIP])
    assert response.headers["content-disposition"] == 'attachment; filename="My-Notes.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == "application/octet-stream"
    assert "no-store" in response.headers["cache-control"]


def test_deleting_a_document_removes_its_file_pages_and_passages(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    document = add_ready(api, database_dsn, store, alice, goal)
    assert list(Path(store._root).rglob("*.txt"))  # pyright: ignore[reportPrivateUsage]

    response = api.delete(f"/v1/documents/{document['id']}", headers=alice.headers)

    assert response.status_code == 204
    assert get(api, alice, document["id"]).status_code == 404
    assert list(Path(store._root).rglob("*.txt")) == []  # pyright: ignore[reportPrivateUsage]
    for table in ("document_pages", "document_chunks"):
        left = admin(database_dsn).fetchone(
            f"select count(*) as n from public.{table} where document_id = %s",  # noqa: S608
            (document["id"],),
        )
        assert left is not None and left["n"] == 0
    assert search(api, alice, goal, "ownership").json()["enough_evidence"] is False
    # Its job went with it, and the same file can be added again.
    assert upload(api, alice, goal, OWNERSHIP.encode()).status_code == 202


def test_a_document_that_is_being_processed_cannot_be_deleted(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    created = upload(api, alice, goal, OWNERSHIP.encode()).json()
    admin(database_dsn).execute(
        "update public.source_documents set status = 'processing' where id = %s", (created["id"],)
    )

    response = api.delete(f"/v1/documents/{created['id']}", headers=alice.headers)

    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_BUSY"
    assert list(Path(store._root).rglob("*.txt"))  # pyright: ignore[reportPrivateUsage]


def test_deleting_an_archived_goal_removes_its_files_and_a_live_goal_keeps_them(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    add_ready(api, database_dsn, store, alice, goal)
    other = create_goal(api, alice, title="Another")["id"]
    add_ready(api, database_dsn, store, alice, other, b"different words about lifetimes")
    root = Path(store._root)  # pyright: ignore[reportPrivateUsage]

    blocked = api.delete(f"/v1/goals/{goal}", headers=alice.headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == "GOAL_NOT_ARCHIVED"
    assert len(list(root.rglob("*.txt"))) == 2

    set_status(api, alice, goal, "archived")
    gone = api.delete(f"/v1/goals/{goal}", headers=alice.headers)

    assert gone.status_code == 204
    assert len(list(root.rglob("*.txt"))) == 1  # only the other goal's file is left
    left = admin(database_dsn).fetchone(
        "select count(*) as n from public.source_documents where goal_id = %s", (goal,)
    )
    assert left is not None and left["n"] == 0


# --- Search -----------------------------------------------------------------------------------


def test_search_returns_real_passages_with_what_a_citation_needs(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    pdf = make_pdf([OWNERSHIP, BORROWING])
    document = add_ready(api, database_dsn, store, alice, goal, pdf, "rust.pdf")

    result = search(api, alice, goal, "What does ownership mean in Rust?")

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["enough_evidence"] is True and body["searched_documents"] == 1
    hit = body["items"][0]
    assert hit["document_id"] == document["id"] and hit["document_title"] == "rust"
    assert "Ownership" in hit["content"] and hit["page_start"] >= 1
    assert hit["position"].startswith(("p.", "pp.")) and hit["similarity"] > 0.1
    row = admin(database_dsn).fetchone(
        "select content, page_start, page_end from public.document_chunks where id = %s",
        (hit["chunk_id"],),
    )
    assert row is not None and row["content"] == hit["content"]  # the id is real


def test_a_question_the_material_does_not_cover_says_so(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    add_ready(api, database_dsn, store, alice, goal)

    result = search(api, alice, goal, "How do I bake sourdough bread at home?").json()

    assert result["enough_evidence"] is False and result["items"] == []
    assert result["searched_documents"] == 1


def test_searching_with_nothing_ready_does_not_call_the_model(
    api: TestClient, api_app: FastAPI, store: LocalFiles, alice: Learner, goal: str
) -> None:
    provider = FakeProvider()
    api_app.state.provider = provider

    result = search(api, alice, goal, "anything at all").json()

    assert result == {"items": [], "enough_evidence": False, "searched_documents": 0}
    assert provider.embedded == []


def test_one_learner_can_never_retrieve_anothers_passages(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, bob: Learner, goal: str
) -> None:
    private_note = "Alice private plan: the vault code discussion happens on Thursday morning."
    mine = add_ready(api, database_dsn, store, alice, goal, private_note.encode())
    bobs_goal = create_goal(api, bob, title="Bob's goal")["id"]
    bobs = add_ready(
        api, database_dsn, store, bob, bobs_goal, b"Bob notes about vault code storage"
    )

    for question in ("vault code discussion Thursday", "private plan"):
        found = search(api, bob, bobs_goal, question).json()
        assert {hit["document_id"] for hit in found["items"]} <= {bobs["id"]}
        assert mine["id"] not in str(found)
        asked_for_hers = search(api, bob, bobs_goal, question, document_ids=[mine["id"]]).json()
        assert asked_for_hers == {"items": [], "enough_evidence": False, "searched_documents": 0}
    assert search(api, bob, goal, "vault code").status_code == 404  # Alice's goal


def test_search_requests_are_validated_and_rate_limited(
    api: TestClient,
    api_app: FastAPI,
    database_dsn: str,
    store: LocalFiles,
    alice: Learner,
    goal: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_ready(api, database_dsn, store, alice, goal)
    assert search(api, alice, goal, "x").status_code == 422
    assert search(api, alice, goal, "y" * 501).status_code == 422
    assert search(api, alice, goal, "ownership", limit=0).status_code == 422
    assert search(api, alice, goal, "ownership", user_id=str(alice.id)).status_code == 422

    monkeypatch.setattr(api_app.state, "search_limiter", SlidingWindowLimiter(2, 3600))
    assert search(api, alice, goal, "ownership rule").status_code == 200
    assert search(api, alice, goal, "ownership rule").status_code == 200
    limited = search(api, alice, goal, "ownership rule")
    assert limited.status_code == 429 and limited.json()["code"] == "SEARCH_RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1


def test_searching_needs_the_ai_service(
    api: TestClient, api_app: FastAPI, database_dsn: str, store: LocalFiles,
    alice: Learner, goal: str, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    add_ready(api, database_dsn, store, alice, goal)
    monkeypatch.setattr(api_app.state, "provider", None)

    response = search(api, alice, goal, "ownership")

    assert response.status_code == 503 and response.json()["code"] == "AI_NOT_CONFIGURED"


@pytest.fixture(autouse=True)
def _forget_files(api_app: FastAPI) -> Iterator[None]:
    yield
    # Never leave a temporary store (or a fake provider) on the shared application.
    api_app.state.files = None


# --- The acceptance path: upload, process, retrieve, then a lesson grounded in the passages ----


def topic_of(roadmap: dict[str, Any]) -> dict[str, Any]:
    return roadmap["modules"][0]["topics"][0]


def test_a_lesson_is_grounded_in_passages_from_an_uploaded_document(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    roadmap = generate_roadmap(api, database_dsn, alice, goal)
    topic = topic_of(roadmap)
    material = (
        f"{topic['title']}. {topic['description']} In this course the key rule is that every "
        "value has exactly one owner, and moving a value transfers that ownership."
    )
    document = add_ready(api, database_dsn, store, alice, goal, material.encode(), "course.txt")
    assert document["status"] == "ready"

    # 1. The passage is retrievable.
    found = search(api, alice, goal, topic["title"]).json()
    assert found["enough_evidence"] is True
    chunk_id = found["items"][0]["chunk_id"]

    # 2. A lesson for the topic is written from it, with the real passage cited.
    clear_queue(database_dsn)
    started = api.post(f"/v1/roadmap-items/{topic['id']}/lessons", headers=alice.headers, json={})
    assert started.status_code == 202, started.text
    assert run_worker_once(database_dsn, files=store) is True
    job = api.get(f"/v1/jobs/{started.json()['id']}", headers=alice.headers).json()
    assert job["status"] == "completed", job

    study = api.get(f"/v1/roadmap-items/{topic['id']}/study", headers=alice.headers).json()
    lesson = study["lesson"]
    assert lesson["content"]["grounding"] == "sources"
    (citation,) = lesson["citations"]
    assert citation["available"] is True and citation["chunk_id"] == chunk_id
    assert citation["document_id"] == document["id"] and citation["document_title"] == "course"
    assert (
        citation["position"] == "part 1"
        and "every value has exactly one owner" in citation["excerpt"]
    )
    assert [r["chunk_id"] for r in lesson["content"]["source_references"]] == [chunk_id]
    assert "every value has exactly one owner" in str(lesson["content"]["sections"])

    # 3. Deleting the document leaves the lesson but not a copy of the document: the citation
    #    is shown as unavailable and carries no text.
    assert api.delete(f"/v1/documents/{document['id']}", headers=alice.headers).status_code == 204
    after = api.get(f"/v1/roadmap-items/{topic['id']}/study", headers=alice.headers).json()
    (gone,) = after["lesson"]["citations"]
    assert gone["available"] is False
    assert gone["excerpt"] is None and gone["document_title"] is None


def test_a_lesson_says_so_when_the_documents_do_not_cover_the_topic(
    api: TestClient, database_dsn: str, store: LocalFiles, alice: Learner, goal: str
) -> None:
    roadmap = generate_roadmap(api, database_dsn, alice, goal)
    topic = topic_of(roadmap)
    add_ready(
        api, database_dsn, store, alice, goal, b"Risotto needs warm stock and patient stirring"
    )

    clear_queue(database_dsn)
    started = api.post(f"/v1/roadmap-items/{topic['id']}/lessons", headers=alice.headers, json={})
    assert run_worker_once(database_dsn, files=store) is True

    study = api.get(f"/v1/roadmap-items/{topic['id']}/study", headers=alice.headers).json()
    assert study["lesson"]["content"]["grounding"] == "no_match"
    assert study["lesson"]["citations"] == []
    assert (
        api.get(f"/v1/jobs/{started.json()['id']}", headers=alice.headers).json()["status"]
        == "completed"
    )
