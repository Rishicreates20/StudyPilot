"""Where uploaded files are kept: a private bucket, reached with the learner's own token.

Two stores share one small interface:

* ``SupabaseFiles``: a **private** Supabase Storage bucket. Row Level Security on
  ``storage.objects`` lets a signed-in learner write, read and delete only objects under their own
  ``{user_id}/`` prefix (see the documents migration), and the API forwards *the learner's own
  access token*: this project never holds the service-role key (CLAUDE.md, ADR-040). The worker
  has no token, so the API mints a **short-lived signed link** for one object when it queues the
  job (``grant_read``) and the worker reads through that link and nothing else.
* ``LocalFiles``: a folder on this machine, for local development and tests. Refused in staging
  and production.

Objects are never public and never served inline: a download goes through the API (with a
``Content-Disposition: attachment`` header and ``nosniff``), so a stored file cannot be opened as a
web page on this site's origin.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx2
import structlog

from app.core.config import DocumentStorageName, Settings

log = structlog.get_logger("app.documents.storage")

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TIMEOUT_SECONDS = 60.0


class StorageError(Exception):
    """A storage call failed. ``code`` is stable, ``message`` is safe for a learner."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ObjectRef:
    """What a job carries to read one stored file: a signed link or a local path, never a key."""

    kind: Literal["supabase", "local"]
    value: str

    def to_json(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}

    @staticmethod
    def from_json(raw: object) -> ObjectRef | None:
        if not isinstance(raw, dict):
            return None
        data: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
        kind, value = data.get("kind"), data.get("value")
        if kind in {"supabase", "local"} and isinstance(value, str) and value:
            return ObjectRef(kind=kind, value=value)  # pyright: ignore[reportArgumentType]
        return None


class DocumentFiles(Protocol):
    """The operations on stored files. ``token`` is the learner's access token (ignored locally)."""

    async def put(self, path: str, data: bytes, mime_type: str, *, token: str) -> None: ...

    async def get(self, path: str, *, token: str) -> bytes: ...

    async def delete(self, path: str, *, token: str) -> None: ...

    async def grant_read(self, path: str, *, token: str) -> ObjectRef: ...

    async def read(self, ref: ObjectRef) -> bytes:
        """Worker side: read through a link made by ``grant_read``. Needs no token."""
        ...


def object_path(user_id: object, document_id: object, safe_name: str) -> str:
    """``{user_id}/{document_id}/{safe_name}``: the learner's own prefix, then the document."""
    return f"{user_id}/{document_id}/{safe_name}"


# --- A folder on this machine ------------------------------------------------------------------


class LocalFiles:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _file(self, path: str) -> Path:
        parts = path.split("/")
        if not 2 <= len(parts) <= 4 or not all(_SEGMENT.match(part) for part in parts):
            raise StorageError("STORAGE_REJECTED", "That file path is not allowed.")
        target = self._root.joinpath(*parts).resolve()
        if self._root not in target.parents:
            raise StorageError("STORAGE_REJECTED", "That file path is not allowed.")
        return target

    async def put(self, path: str, data: bytes, mime_type: str, *, token: str) -> None:
        target = self._file(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise StorageError("STORAGE_REJECTED", "A file is already stored at that path.")
        target.write_bytes(data)

    async def get(self, path: str, *, token: str) -> bytes:
        target = self._file(path)
        if not target.is_file():
            raise StorageError("STORAGE_NOT_FOUND", "The stored file is missing.")
        return target.read_bytes()

    async def delete(self, path: str, *, token: str) -> None:
        target = self._file(path)
        target.unlink(missing_ok=True)
        for folder in (target.parent, target.parent.parent):
            try:
                folder.rmdir()  # only if now empty
            except OSError:
                break

    async def grant_read(self, path: str, *, token: str) -> ObjectRef:
        self._file(path)  # validates the path
        return ObjectRef(kind="local", value=path)

    async def read(self, ref: ObjectRef) -> bytes:
        if ref.kind != "local":
            raise StorageError("STORAGE_REJECTED", "That file is not stored on this machine.")
        return await self.get(ref.value, token="")


# --- Supabase Storage, with the learner's own token --------------------------------------------


class SupabaseFiles:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        base_url: str,
        bucket: str,
        publishable_key: str,
        signed_seconds: int,
    ) -> None:
        self._client = client
        self._root = f"{base_url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._key = publishable_key
        self._signed_seconds = signed_seconds

    def _object(self, path: str, *, flavour: str = "") -> str:
        prefix = f"{flavour}/" if flavour else ""
        return f"{self._root}/object/{prefix}{self._bucket}/{quote(path, safe='/')}"

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "apikey": self._key}

    async def _send(
        self, method: str, url: str, *, accept: set[int] | None = None, **kwargs: Any
    ) -> httpx2.Response:
        try:
            response = await self._client.request(method, url, timeout=_TIMEOUT_SECONDS, **kwargs)
        except httpx2.TimeoutException:
            raise StorageError(
                "STORAGE_UNAVAILABLE", "File storage took too long to answer.", retryable=True
            ) from None
        except httpx2.TransportError:
            raise StorageError(
                "STORAGE_UNAVAILABLE", "File storage can't be reached right now.", retryable=True
            ) from None
        if response.is_success or response.status_code in (accept or set()):
            return response
        status = response.status_code
        log.warning("storage.failed", method=method, status=status)
        if status == 404:
            raise StorageError("STORAGE_NOT_FOUND", "The stored file is missing.")
        if status in {401, 403}:
            raise StorageError("STORAGE_FORBIDDEN", "File storage refused this request.")
        if status == 413:
            raise StorageError("FILE_TOO_LARGE", "File storage refused a file that large.")
        if status in {408, 429} or status >= 500:
            raise StorageError(
                "STORAGE_UNAVAILABLE", "File storage is busy. Please try again.", retryable=True
            )
        raise StorageError("STORAGE_REJECTED", "File storage refused this file.")

    async def put(self, path: str, data: bytes, mime_type: str, *, token: str) -> None:
        await self._send(
            "POST",
            self._object(path),
            content=data,
            headers={**self._headers(token), "Content-Type": mime_type, "x-upsert": "false"},
        )

    async def get(self, path: str, *, token: str) -> bytes:
        response = await self._send(
            "GET", self._object(path, flavour="authenticated"), headers=self._headers(token)
        )
        return response.content

    async def delete(self, path: str, *, token: str) -> None:
        # Already gone is what the caller wanted.
        await self._send("DELETE", self._object(path), headers=self._headers(token), accept={404})

    async def grant_read(self, path: str, *, token: str) -> ObjectRef:
        response = await self._send(
            "POST",
            self._object(path, flavour="sign"),
            headers=self._headers(token),
            json={"expiresIn": self._signed_seconds},
        )
        try:
            signed = response.json()["signedURL"]
        except ValueError, KeyError, TypeError:
            raise StorageError(
                "STORAGE_REJECTED", "File storage did not return a link for this file."
            ) from None
        wanted = f"/object/sign/{self._bucket}/"
        if not isinstance(signed, str) or not signed.startswith(wanted):
            raise StorageError("STORAGE_REJECTED", "File storage returned an unexpected link.")
        return ObjectRef(kind="supabase", value=signed)

    async def read(self, ref: ObjectRef) -> bytes:
        wanted = f"/object/sign/{self._bucket}/"
        if ref.kind != "supabase" or not ref.value.startswith(wanted) or ".." in ref.value:
            raise StorageError("STORAGE_REJECTED", "That link is not one this server made.")
        # The host is always this project's own: only the path and token come from the job.
        response = await self._send("GET", f"{self._root}{ref.value}")
        return response.content


def build_document_files(settings: Settings, client: httpx2.AsyncClient) -> DocumentFiles | None:
    """The configured store, or None when it needs settings that are missing."""
    if settings.document_storage is DocumentStorageName.LOCAL:
        return LocalFiles(settings.document_local_dir)
    if settings.supabase_url is None or settings.supabase_publishable_key is None:
        return None
    return SupabaseFiles(
        client,
        base_url=settings.supabase_url,
        bucket=settings.document_bucket,
        publishable_key=settings.supabase_publishable_key,
        signed_seconds=settings.document_signed_url_seconds,
    )
