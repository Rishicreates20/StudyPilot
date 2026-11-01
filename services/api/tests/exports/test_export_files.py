"""Where exported files are kept: Supabase Storage against a mock transport, and a local folder.

The Supabase calls follow storage-js (createSignedUploadUrl, uploadToSignedUrl, createSignedUrl).
They have never run against a real Storage service (CI's Supabase stack has none).
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from app.core.config import AppEnv, DocumentStorageName
from app.documents.storage import StorageError
from app.exports.files import (
    LOCAL_GRANT,
    LocalExportFiles,
    SupabaseExportFiles,
    build_export_files,
    object_path,
)
from support.settings import IsolatedSettings

pytestmark = pytest.mark.anyio

USER = "0a1b2c3d-0000-4000-8000-000000000001"
EXPORT = "0a1b2c3d-0000-4000-8000-0000000000e1"
PATH = object_path(USER, EXPORT, "notes_pdf")
BEARER = "learner-access-token-xyz"
UNUSED = ""  # the local store takes no token
ROOT = "https://project.supabase.test/storage/v1"
GRANT = f"/object/upload/sign/exports/{PATH}?token=upload-token-abc"


def storage(handler: Callable[[httpx2.Request], httpx2.Response]) -> SupabaseExportFiles:
    return SupabaseExportFiles(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        base_url="https://project.supabase.test",
        bucket="exports",
        publishable_key="sb_publishable_public",
        download_seconds=120,
    )


def test_an_exports_object_lives_under_the_learners_prefix_then_the_export() -> None:
    assert f"{USER}/{EXPORT}/file.pdf" == PATH
    assert object_path(USER, EXPORT, "slides_pptx").endswith("/file.pptx")


# --- Supabase Storage ---------------------------------------------------------------------------


async def test_an_upload_grant_is_asked_for_with_the_learners_token_and_allows_replacing() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"url": GRANT})

    grant = await storage(handler).grant_upload(PATH, token=BEARER)

    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == f"{ROOT}/object/upload/sign/exports/{PATH}"
    assert request.headers["authorization"] == f"Bearer {BEARER}"
    assert request.headers["apikey"] == "sb_publishable_public"
    assert request.headers["x-upsert"] == "true"  # a retried job overwrites, never duplicates
    assert grant == GRANT


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"url": 42},
        {"url": "/object/upload/sign/documents/x/y/file.pdf?token=t"},  # another bucket
        {"url": f"/object/upload/sign/exports/{PATH}"},  # no token
        {"url": "/object/upload/sign/exports/../other/file.pdf?token=t"},
        {"url": "https://evil.example/object/upload/sign/exports/a?token=t"},
    ],
)
async def test_an_unexpected_upload_grant_is_refused(reply: dict[str, object]) -> None:
    with pytest.raises(StorageError) as raised:
        await storage(lambda _r: httpx2.Response(200, json=reply)).grant_upload(PATH, token=BEARER)
    assert raised.value.code == "STORAGE_REJECTED"


async def test_the_worker_uploads_through_the_grant_without_any_learner_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"Key": f"exports/{PATH}"})

    await storage(handler).upload(GRANT, b"%PDF-1.7 bytes", "application/pdf")

    (request,) = seen
    assert request.method == "PUT"
    assert str(request.url) == f"{ROOT}{GRANT}"  # always this project's own host
    assert "authorization" not in request.headers
    assert request.headers["apikey"] == "sb_publishable_public"
    assert request.headers["content-type"] == "application/pdf"
    assert request.headers["x-upsert"] == "true"
    assert request.content == b"%PDF-1.7 bytes"


@pytest.mark.parametrize(
    "grant",
    [
        "https://evil.example/storage/v1/object/upload/sign/exports/a?token=t",
        "/object/sign/exports/a?token=t",  # a download link, not an upload one
        "/object/upload/sign/exports/../../x?token=t",
        "local:somewhere",
    ],
)
async def test_the_worker_uploads_only_through_grants_this_server_made(grant: str) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request may be sent")

    with pytest.raises(StorageError):
        await storage(handler).upload(grant, b"data", "application/pdf")


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "STORAGE_REJECTED", False),  # an expired or tampered upload token
        (403, "STORAGE_FORBIDDEN", False),
        (413, "FILE_TOO_LARGE", False),
        (503, "STORAGE_UNAVAILABLE", True),
    ],
)
async def test_upload_failures_say_whether_to_try_again(
    status: int, code: str, retryable: bool
) -> None:
    with pytest.raises(StorageError) as raised:
        await storage(lambda _r: httpx2.Response(status, json={"error": "x"})).upload(
            GRANT, b"data", "application/pdf"
        )
    assert (raised.value.code, raised.value.retryable) == (code, retryable)


async def test_a_download_link_is_signed_short_lived_and_forces_a_download() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"signedURL": f"/object/sign/exports/{PATH}?token=dl"})

    link = await storage(handler).download_link(
        PATH, token=BEARER, file_name="rust-ownership-notes.pdf"
    )

    (request,) = seen
    assert str(request.url) == f"{ROOT}/object/sign/exports/{PATH}"
    assert request.headers["authorization"] == f"Bearer {BEARER}"
    assert json.loads(request.read()) == {"expiresIn": 120}
    assert link == (f"{ROOT}/object/sign/exports/{PATH}?token=dl&download=rust-ownership-notes.pdf")
    assert BEARER not in link


# --- A folder on this machine ---------------------------------------------------------------------


async def test_a_local_export_is_uploaded_replaced_read_and_deleted(tmp_path: Path) -> None:
    files = LocalExportFiles(tmp_path)
    grant = await files.grant_upload(PATH, token=UNUSED)
    assert grant == LOCAL_GRANT + PATH

    await files.upload(grant, b"first", "application/pdf")
    await files.upload(grant, b"second", "application/pdf")  # a retry replaces the file
    assert await files.get(PATH, token=UNUSED) == b"second"
    assert await files.download_link(PATH, token=UNUSED, file_name="x.pdf") is None

    await files.delete(PATH, token=UNUSED)
    with pytest.raises(StorageError):
        await files.get(PATH, token=UNUSED)


@pytest.mark.parametrize(
    "grant",
    [f"{LOCAL_GRANT}../escape/file.pdf", f"{LOCAL_GRANT}a", "/object/upload/sign/x?token=t"],
)
async def test_a_local_upload_cannot_leave_its_folder(tmp_path: Path, grant: str) -> None:
    with pytest.raises(StorageError):
        await LocalExportFiles(tmp_path / "exports").upload(grant, b"x", "application/pdf")
    assert not (tmp_path / "escape").exists()


# --- Choosing the store ---------------------------------------------------------------------------


async def test_the_store_follows_the_document_storage_setting(tmp_path: Path) -> None:
    async with httpx2.AsyncClient() as client:
        local = IsolatedSettings(
            app_env=AppEnv.TEST,
            document_storage=DocumentStorageName.LOCAL,
            export_local_dir=str(tmp_path),
        )
        assert isinstance(build_export_files(local, client), LocalExportFiles)

        missing_key = IsolatedSettings(
            app_env=AppEnv.TEST, supabase_url="https://project.supabase.test"
        )
        assert build_export_files(missing_key, client) is None

        supabase = IsolatedSettings(
            app_env=AppEnv.TEST,
            supabase_url="https://project.supabase.test",
            supabase_publishable_key="sb_publishable_public",
        )
        assert isinstance(build_export_files(supabase, client), SupabaseExportFiles)
