"""Exports through the HTTP API with the real worker: request, status, download, delete.

Files go to a temporary local store (``LocalExportFiles``); the Supabase store is tested against a
mock transport in ``tests/exports/test_export_files.py``.
"""

import io
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from pptx import Presentation
from pypdf import PdfReader

from app.documents.storage import LocalFiles, StorageError
from app.exports.files import LocalExportFiles
from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status, topic_ids
from support.database import admin
from support.quiz_api import write_lesson
from support.worker import clear_queue, run_worker_once

MakeLearner = Callable[..., Learner]
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.fixture
def store(api_app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalExportFiles:
    files = LocalExportFiles(tmp_path / "exports")
    monkeypatch.setattr(api_app.state, "export_files", files)
    return files


@pytest.fixture
def owned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a goal, a roadmap and a written lesson; Bob with nothing."""
    alice, bob = make_learner(), make_learner()
    goal = create_goal(api, alice)
    roadmap = generate_roadmap(api, database_dsn, alice, goal["id"])
    job = write_lesson(api, database_dsn, alice, topic_ids(roadmap)[0])
    return {
        "alice": alice,
        "bob": bob,
        "goal": goal["id"],
        "roadmap": roadmap["id"],
        "lesson": job["lesson_id"],
    }


def export_lesson(
    api: TestClient, learner: Learner, lesson: str, fmt: str = "notes_pdf"
) -> Response:
    return api.post(f"/v1/lessons/{lesson}/exports", headers=learner.headers, json={"format": fmt})


def export_roadmap(
    api: TestClient, learner: Learner, roadmap: str, fmt: str = "roadmap_pdf"
) -> Response:
    return api.post(
        f"/v1/roadmaps/{roadmap}/exports", headers=learner.headers, json={"format": fmt}
    )


def make(dsn: str, store: Any) -> None:
    """Run the queued export job with the real worker."""
    assert run_worker_once(dsn, export_files=store) is True


def export_jobs(dsn: str, export_id: str) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select status, error_code from public.generation_jobs where export_id = %s"
        " order by created_at",
        (export_id,),
    )
    return [dict(row) for row in rows]


# --- The whole journey ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "fmt", "content_type"),
    [
        ("lesson", "notes_pdf", "application/pdf"),
        ("lesson", "revision_pdf", "application/pdf"),
        ("lesson", "slides_pptx", PPTX),
        ("roadmap", "roadmap_pdf", "application/pdf"),
        ("roadmap", "slides_pptx", PPTX),
    ],
)
def test_a_learner_requests_follows_and_downloads_an_export(
    api: TestClient,
    database_dsn: str,
    store: LocalExportFiles,
    owned: dict[str, Any],
    kind: str,
    fmt: str,
    content_type: str,
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    response = (
        export_lesson(api, alice, owned["lesson"], fmt)
        if kind == "lesson"
        else export_roadmap(api, alice, owned["roadmap"], fmt)
    )
    assert response.status_code == 202, response.text
    export = response.json()
    assert export["status"] == "processing" and export["format"] == fmt
    assert export["job"]["job_type"] == "export" and export["job"]["export_id"] == export["id"]
    assert export["goal_id"] == owned["goal"]
    assert export["file_name"] is None
    assert export["source_title"] and export["source_version"] >= 1  # what the file is made from

    make(database_dsn, store)

    ready = api.get(f"/v1/exports/{export['id']}", headers=alice.headers).json()
    assert ready["status"] == "ready", ready
    assert ready["content_type"] == content_type
    assert ready["page_count"] >= 1 and ready["size_bytes"] > 1000
    assert ready["unsupported_characters"] == 0
    assert ready["job"]["status"] == "completed"
    assert "storage_path" not in ready and "upload_token" not in ready

    link = api.post(f"/v1/exports/{export['id']}/download-link", headers=alice.headers)
    assert link.status_code == 200
    assert link.json() == {"url": None, "expires_at": None, "file_name": ready["file_name"]}

    file = api.get(f"/v1/exports/{export['id']}/file", headers=alice.headers)
    assert file.status_code == 200
    assert file.headers["content-type"] == content_type
    assert file.headers["content-disposition"] == f'attachment; filename="{ready["file_name"]}"'
    assert file.headers["x-content-type-options"] == "nosniff"
    assert file.headers["cache-control"] == "private, no-store"
    assert len(file.content) == ready["size_bytes"]
    if content_type == PPTX:
        assert len(Presentation(io.BytesIO(file.content)).slides) == ready["page_count"]
    else:
        assert len(PdfReader(io.BytesIO(file.content)).pages) == ready["page_count"]

    # The upload capability is gone once the file is stored.
    token = admin(database_dsn).scalar(
        "select upload_token from public.exports where id = %s", (export["id"],)
    )
    assert token is None


def test_asking_again_returns_the_same_export_without_a_new_job(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    first = export_lesson(api, alice, owned["lesson"]).json()

    while_busy = export_lesson(api, alice, owned["lesson"])
    assert while_busy.status_code == 200 and while_busy.json()["id"] == first["id"]

    make(database_dsn, store)
    after = export_lesson(api, alice, owned["lesson"])
    assert after.status_code == 200
    assert after.json()["id"] == first["id"] and after.json()["status"] == "ready"
    assert len(export_jobs(database_dsn, first["id"])) == 1

    listed = api.get(f"/v1/goals/{owned['goal']}/exports", headers=alice.headers).json()
    assert [item["id"] for item in listed["items"]] == [first["id"]]
    assert listed["items"][0]["status"] == "ready"


# --- Failure and recovery -------------------------------------------------------------------------


class FailingStore(LocalExportFiles):
    """Uploads fail with a chosen storage error; everything else works."""

    def __init__(self, root: Path, error: StorageError) -> None:
        super().__init__(root)
        self.error = error

    async def upload(self, grant: str, data: bytes, content_type: str) -> None:
        raise self.error


def test_a_storage_hiccup_is_retried_and_an_expired_link_fails_until_asked_again(
    api: TestClient,
    database_dsn: str,
    store: LocalExportFiles,
    owned: dict[str, Any],
    tmp_path: Path,
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()

    busy = FailingStore(
        tmp_path / "exports", StorageError("STORAGE_UNAVAILABLE", "busy", retryable=True)
    )
    make(database_dsn, busy)
    jobs = export_jobs(database_dsn, export["id"])
    assert jobs == [{"status": "queued", "error_code": "STORAGE_UNAVAILABLE"}]  # will retry
    assert api.get(f"/v1/exports/{export['id']}", headers=alice.headers).json()["status"] == (
        "processing"
    )

    expired = FailingStore(tmp_path / "exports", StorageError("STORAGE_REJECTED", "bad token"))
    make(database_dsn, expired)
    failed = api.get(f"/v1/exports/{export['id']}", headers=alice.headers).json()
    assert failed["status"] == "failed"
    assert failed["job"]["error_code"] == "EXPORT_LINK_EXPIRED"
    assert "Ask for the export again" in failed["job"]["error_message"]
    assert (
        admin(database_dsn).scalar(
            "select upload_token from public.exports where id = %s", (export["id"],)
        )
        is None
    )  # the dead capability was dropped

    again = export_lesson(api, alice, owned["lesson"])
    assert again.status_code == 202 and again.json()["id"] == export["id"]
    make(database_dsn, store)
    assert api.get(f"/v1/exports/{export['id']}", headers=alice.headers).json()["status"] == "ready"
    assert [j["status"] for j in export_jobs(database_dsn, export["id"])] == ["failed", "completed"]


class CancellingStore(LocalExportFiles):
    """The learner cancels while the file is being uploaded: after the lease's last look, before
    the transaction that would record the file."""

    def __init__(self, root: Path, dsn: str) -> None:
        super().__init__(root)
        self.dsn = dsn

    async def upload(self, grant: str, data: bytes, content_type: str) -> None:
        await super().upload(grant, data, content_type)
        admin(self.dsn).execute(
            "update public.generation_jobs set cancel_requested = true"
            " where job_type = 'export' and status = 'running'"
        )


def test_a_cancel_that_lands_while_the_file_is_uploaded_wins(
    api: TestClient,
    database_dsn: str,
    store: LocalExportFiles,
    owned: dict[str, Any],
    tmp_path: Path,
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()

    make(database_dsn, CancellingStore(tmp_path / "exports", database_dsn))

    assert [j["status"] for j in export_jobs(database_dsn, export["id"])] == ["cancelled"]
    row = admin(database_dsn).fetchone(
        "select ready_at, upload_token from public.exports where id = %s", (export["id"],)
    )
    assert row is not None and row["ready_at"] is None and row["upload_token"] is None
    assert api.get(f"/v1/exports/{export['id']}", headers=alice.headers).json()["status"] == (
        "failed"
    )


def test_a_download_link_is_refused_until_the_file_is_ready(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()
    for response in (
        api.post(f"/v1/exports/{export['id']}/download-link", headers=alice.headers),
        api.get(f"/v1/exports/{export['id']}/file", headers=alice.headers),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "EXPORT_NOT_READY"


# --- Rules ----------------------------------------------------------------------------------------


def test_a_format_that_does_not_fit_the_source_or_an_extra_field_is_refused(
    api: TestClient, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    assert export_lesson(api, alice, owned["lesson"], "roadmap_pdf").status_code == 422
    assert export_roadmap(api, alice, owned["roadmap"], "notes_pdf").status_code == 422
    sneaky = api.post(
        f"/v1/lessons/{owned['lesson']}/exports",
        headers=alice.headers,
        json={"format": "notes_pdf", "goal_id": owned["goal"]},
    )
    assert sneaky.status_code == 422


def test_an_archived_goal_cannot_be_exported(
    api: TestClient, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    set_status(api, alice, owned["goal"], "archived")
    for response in (
        export_lesson(api, alice, owned["lesson"]),
        export_roadmap(api, alice, owned["roadmap"]),
    ):
        assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"


class ArchivingStore(LocalExportFiles):
    """Archives the goal while the API is making the upload link: a request from another tab that
    lands between the API's first check and the transaction that queues the job."""

    def __init__(self, root: Path, dsn: str, goal_id: str) -> None:
        super().__init__(root)
        self.dsn = dsn
        self.goal_id = goal_id

    async def grant_upload(self, path: str, *, token: str) -> str:
        admin(self.dsn).execute(
            "update public.learning_goals set status = 'archived' where id = %s", (self.goal_id,)
        )
        return await super().grant_upload(path, token=token)


@pytest.mark.parametrize("kind", ["lesson", "roadmap"])
def test_a_goal_archived_while_an_export_is_asked_for_gets_no_job(
    api: TestClient,
    api_app: FastAPI,
    database_dsn: str,
    owned: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    store = ArchivingStore(tmp_path / "exports", database_dsn, owned["goal"])
    monkeypatch.setattr(api_app.state, "export_files", store)

    if kind == "lesson":
        response = export_lesson(api, alice, owned["lesson"])
    else:
        response = export_roadmap(api, alice, owned["roadmap"])

    assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"
    queued = admin(database_dsn).scalar(
        "select count(*) from public.generation_jobs where job_type = 'export' and goal_id = %s",
        (owned["goal"],),
    )
    assert queued == 0


def test_the_daily_allowance_is_enforced(
    api: TestClient,
    api_app: FastAPI,
    database_dsn: str,
    store: LocalExportFiles,
    owned: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = api_app.state.settings.model_copy(update={"export_jobs_per_user_per_day": 1})
    monkeypatch.setattr(api_app.state, "settings", settings)
    alice = owned["alice"]
    clear_queue(database_dsn)
    assert export_lesson(api, alice, owned["lesson"]).status_code == 202
    second = export_lesson(api, alice, owned["lesson"], "slides_pptx")
    assert second.status_code == 429 and second.json()["code"] == "EXPORT_ALLOWANCE_USED"


def test_exports_need_file_storage(
    api: TestClient, api_app: FastAPI, owned: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_app.state, "export_files", None)
    response = export_lesson(api, owned["alice"], owned["lesson"])
    assert response.status_code == 503 and response.json()["code"] == "STORAGE_NOT_CONFIGURED"


# --- Ownership and authentication -----------------------------------------------------------------


def test_another_learner_gets_404_everywhere(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice, bob = owned["alice"], owned["bob"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()
    make(database_dsn, store)

    responses = [
        export_lesson(api, bob, owned["lesson"]),
        export_roadmap(api, bob, owned["roadmap"]),
        api.get(f"/v1/exports/{export['id']}", headers=bob.headers),
        api.get(f"/v1/goals/{owned['goal']}/exports", headers=bob.headers),
        api.post(f"/v1/exports/{export['id']}/download-link", headers=bob.headers),
        api.get(f"/v1/exports/{export['id']}/file", headers=bob.headers),
        api.delete(f"/v1/exports/{export['id']}", headers=bob.headers),
    ]
    assert [r.status_code for r in responses] == [404] * len(responses)
    assert api.get(f"/v1/exports/{export['id']}", headers=alice.headers).status_code == 200


def test_every_export_endpoint_needs_a_token(api: TestClient) -> None:
    some = uuid.uuid4()
    responses = [
        api.post(f"/v1/lessons/{some}/exports", json={"format": "notes_pdf"}),
        api.post(f"/v1/roadmaps/{some}/exports", json={"format": "roadmap_pdf"}),
        api.get(f"/v1/exports/{some}"),
        api.get(f"/v1/goals/{some}/exports"),
        api.post(f"/v1/exports/{some}/download-link"),
        api.get(f"/v1/exports/{some}/file"),
        api.delete(f"/v1/exports/{some}"),
        api.get(f"/v1/exports/{some}", headers={"Authorization": "Bearer not-a-token"}),
    ]
    assert [r.status_code for r in responses] == [401] * len(responses)


# --- Deleting -------------------------------------------------------------------------------------


def test_deleting_an_export_removes_its_file_but_not_while_it_is_being_made(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()

    busy = api.delete(f"/v1/exports/{export['id']}", headers=alice.headers)
    assert busy.status_code == 409 and busy.json()["code"] == "EXPORT_BUSY"

    make(database_dsn, store)
    path = admin(database_dsn).scalar(
        "select storage_path from public.exports where id = %s", (export["id"],)
    )
    assert path is not None
    stored = store._file(path)  # pyright: ignore[reportPrivateUsage]
    assert stored.is_file()

    assert api.delete(f"/v1/exports/{export['id']}", headers=alice.headers).status_code == 204
    assert not stored.exists()
    assert api.get(f"/v1/exports/{export['id']}", headers=alice.headers).status_code == 404


def test_deleting_a_goal_removes_its_exported_files(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()
    make(database_dsn, store)
    path = admin(database_dsn).scalar(
        "select storage_path from public.exports where id = %s", (export["id"],)
    )
    stored = store._file(path)  # pyright: ignore[reportPrivateUsage]
    assert stored.is_file()

    set_status(api, alice, owned["goal"], "archived")
    assert api.delete(f"/v1/goals/{owned['goal']}", headers=alice.headers).status_code == 204
    assert not stored.exists()


def test_a_live_goal_keeps_its_exported_files_when_deleting_it_is_refused(
    api: TestClient, database_dsn: str, store: LocalExportFiles, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    clear_queue(database_dsn)
    export = export_lesson(api, alice, owned["lesson"]).json()
    make(database_dsn, store)
    path = admin(database_dsn).scalar(
        "select storage_path from public.exports where id = %s", (export["id"],)
    )
    stored = store._file(path)  # pyright: ignore[reportPrivateUsage]

    blocked = api.delete(f"/v1/goals/{owned['goal']}", headers=alice.headers)

    assert blocked.status_code == 409 and blocked.json()["code"] == "GOAL_NOT_ARCHIVED"
    assert stored.is_file()


class UndeletableStore(LocalExportFiles):
    """Exported files cannot be removed: storage is down."""

    async def delete(self, path: str, *, token: str) -> None:
        raise StorageError("STORAGE_UNAVAILABLE", "Storage is unavailable.", retryable=True)


def test_uploaded_documents_are_kept_when_a_goals_exported_files_cannot_be_removed(
    api: TestClient,
    api_app: FastAPI,
    database_dsn: str,
    store: LocalExportFiles,
    owned: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exported files go first: they can be made again, the learner's own documents cannot."""
    alice, goal = owned["alice"], owned["goal"]
    clear_queue(database_dsn)
    export_lesson(api, alice, owned["lesson"])
    make(database_dsn, store)
    documents = LocalFiles(tmp_path / "files")
    monkeypatch.setattr(api_app.state, "files", documents)
    uploaded = api.post(
        f"/v1/goals/{goal}/documents",
        headers={**alice.headers, "Content-Type": "application/octet-stream"},
        params={"name": "notes.txt"},
        content=b"Ownership means every value has exactly one owner at a time.",
    )
    assert uploaded.status_code == 202
    root = Path(documents._root)  # pyright: ignore[reportPrivateUsage]
    assert len(list(root.rglob("*.txt"))) == 1

    monkeypatch.setattr(api_app.state, "export_files", UndeletableStore(tmp_path / "exports"))
    set_status(api, alice, goal, "archived")
    response = api.delete(f"/v1/goals/{goal}", headers=alice.headers)

    assert response.status_code == 503 and response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert len(list(root.rglob("*.txt"))) == 1  # the learner's own file is untouched
    assert api.get(f"/v1/goals/{goal}", headers=alice.headers).status_code == 200


# --- Jobs of a kind this worker cannot run --------------------------------------------------------


def test_a_job_of_an_unknown_kind_fails_instead_of_running_as_a_roadmap(
    database_dsn: str, owned: dict[str, Any]
) -> None:
    clear_queue(database_dsn)
    alice = owned["alice"]
    row = admin(database_dsn).fetchone(
        "select id from public.roadmap_items where roadmap_id = %s and kind = 'topic' limit 1",
        (owned["roadmap"],),
    )
    assert row is not None
    job = admin(database_dsn).fetchone(
        "insert into public.generation_jobs (user_id, goal_id, item_id, job_type)"
        " values (%s, %s, %s, 'resources') returning id",
        (alice.id, owned["goal"], row["id"]),
    )
    assert job is not None
    roadmaps_before = admin(database_dsn).scalar(
        "select count(*) from public.roadmaps where goal_id = %s", (owned["goal"],)
    )

    assert run_worker_once(database_dsn) is True

    state = admin(database_dsn).fetchone(
        "select status, error_code from public.generation_jobs where id = %s", (job["id"],)
    )
    assert state == {"status": "failed", "error_code": "JOB_TYPE_UNSUPPORTED"}
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.roadmaps where goal_id = %s", (owned["goal"],)
        )
        == roadmaps_before
    )
