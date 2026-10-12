"""Where files are kept: a local folder, and Supabase Storage against a mock transport."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.documents.storage import (
    LocalFiles,
    ObjectRef,
    StorageError,
    SupabaseFiles,
    object_path,
)

pytestmark = pytest.mark.anyio

USER = "0a1b2c3d-0000-4000-8000-000000000001"
DOC = "0a1b2c3d-0000-4000-8000-0000000000d1"
PATH = object_path(USER, DOC, "notes.pdf")
BEARER = "learner-access-token-xyz"


# --- A folder on this machine --------------------------------------------------------------------


async def test_a_local_file_can_be_stored_read_and_removed(tmp_path: Path) -> None:
    files = LocalFiles(tmp_path)

    await files.put(PATH, b"hello", "text/plain", token="")
    assert await files.get(PATH, token="") == b"hello"
    ref = await files.grant_read(PATH, token="")
    assert ref == ObjectRef("local", PATH) and await files.read(ref) == b"hello"

    await files.delete(PATH, token="")

    with pytest.raises(StorageError) as caught:
        await files.get(PATH, token="")
    assert caught.value.code == "STORAGE_NOT_FOUND"
    assert not (tmp_path / USER).exists()  # the emptied folders are gone too


async def test_deleting_a_file_that_is_not_there_is_fine(tmp_path: Path) -> None:
    await LocalFiles(tmp_path).delete(PATH, token="")


async def test_a_local_file_is_never_overwritten(tmp_path: Path) -> None:
    files = LocalFiles(tmp_path)
    await files.put(PATH, b"first", "text/plain", token="")

    with pytest.raises(StorageError) as caught:
        await files.put(PATH, b"second", "text/plain", token="")

    assert caught.value.code == "STORAGE_REJECTED" and await files.get(PATH, token="") == b"first"


@pytest.mark.parametrize(
    "path",
    [
        "../outside/file.txt",
        f"{USER}/../../etc/passwd",
        f"{USER}/{DOC}/..",
        "/absolute/path/file.txt",
        f"{USER}/{DOC}/a b.txt",
        f"{USER}/{DOC}/.hidden",
        "onlyone",
        f"{USER}/{DOC}/x/y/z",
        f"{USER}\\{DOC}\\file.txt",
    ],
)
async def test_a_local_path_cannot_leave_the_folder_or_be_odd(tmp_path: Path, path: str) -> None:
    files = LocalFiles(tmp_path)

    for call in (
        files.put(path, b"x", "text/plain", token=""),
        files.get(path, token=""),
        files.delete(path, token=""),
        files.grant_read(path, token=""),
    ):
        with pytest.raises(StorageError) as caught:
            await call
        assert caught.value.code == "STORAGE_REJECTED"


async def test_a_local_store_refuses_a_link_that_is_not_local(tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        await LocalFiles(tmp_path).read(ObjectRef("supabase", "/object/sign/documents/x?token=t"))


def test_an_object_reference_survives_a_round_trip_through_json_and_rejects_junk() -> None:
    ref = ObjectRef("supabase", "/object/sign/documents/a/b/c.pdf?token=t")

    assert ObjectRef.from_json(ref.to_json()) == ref
    junk: list[object] = [None, "x", [], {}, {"kind": "ftp", "value": "x"}]
    junk.append({"kind": "local", "value": ""})
    for raw in junk:
        assert ObjectRef.from_json(raw) is None


# --- Supabase Storage ----------------------------------------------------------------------------


def storage(handler: Callable[[httpx2.Request], httpx2.Response]) -> SupabaseFiles:
    return SupabaseFiles(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        base_url="https://project.supabase.test",
        bucket="documents",
        publishable_key="sb_publishable_public",
        signed_seconds=900,
    )


async def test_an_upload_goes_to_the_private_bucket_with_the_learners_own_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"Key": "documents/x"})

    await storage(handler).put(PATH, b"%PDF-bytes", "application/pdf", token=BEARER)

    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == f"https://project.supabase.test/storage/v1/object/documents/{PATH}"
    assert request.headers["authorization"] == f"Bearer {BEARER}"
    assert request.headers["apikey"] == "sb_publishable_public"
    assert request.headers["content-type"] == "application/pdf"
    assert request.headers["x-upsert"] == "false"
    assert request.content == b"%PDF-bytes"
    assert BEARER not in str(request.url)


async def test_a_download_uses_the_authenticated_route() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=b"file-bytes")

    assert await storage(handler).get(PATH, token=BEARER) == b"file-bytes"

    assert str(seen[0].url).endswith(f"/storage/v1/object/authenticated/documents/{PATH}")
    assert seen[0].headers["authorization"] == f"Bearer {BEARER}"


async def test_a_delete_treats_already_gone_as_done() -> None:
    methods: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        methods.append(request.method)
        return httpx2.Response(404, json={"error": "not found"})

    await storage(handler).delete(PATH, token=BEARER)

    assert methods == ["DELETE"]


async def test_a_signed_link_is_requested_for_one_object_and_checked() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"signedURL": f"/object/sign/documents/{PATH}?token=abc"})

    ref = await storage(handler).grant_read(PATH, token=BEARER)

    assert ref == ObjectRef("supabase", f"/object/sign/documents/{PATH}?token=abc")
    assert seen[0].method == "POST"
    assert str(seen[0].url).endswith(f"/storage/v1/object/sign/documents/{PATH}")
    assert json.loads(seen[0].content) == {"expiresIn": 900}


@pytest.mark.parametrize(
    "reply",
    [
        {"signedURL": "/object/sign/other-bucket/x?token=t"},
        {"signedURL": "https://evil.example/steal"},
        {"signedURL": 5},
        {},
    ],
)
async def test_a_signed_link_for_somewhere_else_is_refused(reply: dict[str, Any]) -> None:
    with pytest.raises(StorageError):
        await storage(lambda _r: httpx2.Response(200, json=reply)).grant_read(PATH, token=BEARER)


async def test_the_worker_reads_through_the_link_on_this_projects_own_host_without_a_token() -> (
    None
):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=b"pdf")

    ref = ObjectRef("supabase", f"/object/sign/documents/{PATH}?token=abc")

    assert await storage(handler).read(ref) == b"pdf"

    assert str(seen[0].url) == (
        f"https://project.supabase.test/storage/v1/object/sign/documents/{PATH}?token=abc"
    )
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/object/sign/documents/x",
        "//evil.example/object/sign/documents/x",
        "/object/sign/other/x?token=t",
        "/object/sign/documents/../../secrets?token=t",
        "/object/public/documents/x",
    ],
)
async def test_a_link_that_does_not_belong_to_this_bucket_is_never_fetched(value: str) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("nothing should be fetched")

    with pytest.raises(StorageError):
        await storage(handler).read(ObjectRef("supabase", value))


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "STORAGE_FORBIDDEN", False),
        (403, "STORAGE_FORBIDDEN", False),
        (404, "STORAGE_NOT_FOUND", False),
        (413, "FILE_TOO_LARGE", False),
        (400, "STORAGE_REJECTED", False),
        (409, "STORAGE_REJECTED", False),
        (429, "STORAGE_UNAVAILABLE", True),
        (500, "STORAGE_UNAVAILABLE", True),
        (503, "STORAGE_UNAVAILABLE", True),
    ],
)
async def test_storage_failures_become_typed_errors(
    status: int, code: str, retryable: bool
) -> None:
    with pytest.raises(StorageError) as caught:
        await storage(lambda _r: httpx2.Response(status, json={"message": "details"})).get(
            PATH, token=BEARER
        )

    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert "details" not in caught.value.message and BEARER not in caught.value.message


async def test_an_unreachable_store_is_retryable_and_says_nothing_about_the_host() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused to project.supabase.test")

    with pytest.raises(StorageError) as caught:
        await storage(handler).put(PATH, b"x", "text/plain", token=BEARER)

    assert caught.value.retryable and "supabase.test" not in caught.value.message
