"""Where exported files are kept: the private ``exports`` bucket (ADR-049).

Same rules as uploaded documents (``app.documents.storage``): a private Supabase Storage bucket
reached with the learner's own token (never the service-role key), objects only under the
learner's ``{user_id}/`` prefix (Storage policies in the exports migration), and a local folder
for development and tests that staging and production refuse.

The worker has no learner token, so it cannot write to Storage by itself. When the API queues an
export it asks Storage, with the learner's token, for a **signed upload link** for exactly one
object (valid for two hours), and stores it on the export row (`exports.upload_token`, a column
learners cannot read back through the Data API). The worker uploads through that link and nothing
else. Downloads use a **signed download link** for one object, valid for a couple of minutes,
minted on request with the learner's token.

Supabase's REST paths were taken from its storage-js client (StorageFileApi: createSignedUploadUrl,
uploadToSignedUrl, createSignedUrl) on 2026-10-23. They have only been exercised against a mock
transport: CI's Supabase stack has no Storage.
"""

from typing import Protocol
from urllib.parse import quote

import httpx2

from app.core.config import DocumentStorageName, Settings
from app.documents.storage import LocalFiles, StorageError, SupabaseFiles

LOCAL_GRANT = "local:"
_EXTENSION = {
    "notes_pdf": "pdf",
    "revision_pdf": "pdf",
    "roadmap_pdf": "pdf",
    "slides_pptx": "pptx",
}


def object_path(user_id: object, export_id: object, export_format: str) -> str:
    """Where an export's file lives: the learner's own prefix, then the export. The database
    requires this shape (``exports_file_under_own_prefix``) and Storage's policies the prefix."""
    return f"{user_id}/{export_id}/file.{_EXTENSION[export_format]}"


class ExportFiles(Protocol):
    async def grant_upload(self, path: str, *, token: str) -> str:
        """A one-object upload capability for the worker, made with the learner's token."""
        ...

    async def upload(self, grant: str, data: bytes, content_type: str) -> None:
        """Worker side: store ``data`` through a grant from ``grant_upload``. Replaces a retry's
        earlier upload of the same object."""
        ...

    async def download_link(self, path: str, *, token: str, file_name: str) -> str | None:
        """A short-lived link that downloads the object as ``file_name``; None when the store
        has no links (the local folder), in which case the API serves the file itself."""
        ...

    async def get(self, path: str, *, token: str) -> bytes: ...

    async def delete(self, path: str, *, token: str) -> None: ...


class SupabaseExportFiles(SupabaseFiles):
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        base_url: str,
        bucket: str,
        publishable_key: str,
        download_seconds: int,
    ) -> None:
        super().__init__(
            client,
            base_url=base_url,
            bucket=bucket,
            publishable_key=publishable_key,
            signed_seconds=download_seconds,
        )
        self._upload_prefix = f"/object/upload/sign/{bucket}/"

    async def grant_upload(self, path: str, *, token: str) -> str:
        response = await self._send(
            "POST",
            self._object(path, flavour="upload/sign"),
            # Upsert: a retried job uploads to the same path again instead of failing.
            headers={**self._headers(token), "x-upsert": "true"},
        )
        try:
            url = response.json()["url"]
        except ValueError, KeyError, TypeError:
            raise StorageError(
                "STORAGE_REJECTED", "File storage did not return an upload link."
            ) from None
        if (
            not isinstance(url, str)
            or not url.startswith(self._upload_prefix)
            or "token=" not in url
            or ".." in url
            or len(url) > 1000
        ):
            raise StorageError("STORAGE_REJECTED", "File storage returned an unexpected link.")
        return url

    async def upload(self, grant: str, data: bytes, content_type: str) -> None:
        if not grant.startswith(self._upload_prefix) or ".." in grant or "token=" not in grant:
            raise StorageError("STORAGE_REJECTED", "That upload link is not one this server made.")
        # The host is always this project's own: only the path and token come from the row.
        await self._send(
            "PUT",
            f"{self._root}{grant}",
            content=data,
            headers={
                # The publishable key, as Supabase's own client sends it; no learner token.
                "apikey": self._key,
                "Content-Type": content_type,
                "x-upsert": "true",
                "cache-control": "max-age=0",
            },
        )

    async def download_link(self, path: str, *, token: str, file_name: str) -> str:
        grant = await self.grant_read(path, token=token)
        return f"{self._root}{grant.value}&download={quote(file_name, safe='')}"


class LocalExportFiles(LocalFiles):
    """Exports in a folder on this machine. No links: the API streams the file instead."""

    async def grant_upload(self, path: str, *, token: str) -> str:
        self._file(path)  # validates the path
        return LOCAL_GRANT + path

    async def upload(self, grant: str, data: bytes, content_type: str) -> None:
        if not grant.startswith(LOCAL_GRANT):
            raise StorageError("STORAGE_REJECTED", "That upload link is not one this server made.")
        target = self._file(grant.removeprefix(LOCAL_GRANT))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def download_link(self, path: str, *, token: str, file_name: str) -> None:
        self._file(path)
        return None


def build_export_files(settings: Settings, client: httpx2.AsyncClient) -> ExportFiles | None:
    """The configured store, or None when it needs settings that are missing."""
    if settings.document_storage is DocumentStorageName.LOCAL:
        return LocalExportFiles(settings.export_local_dir)
    if settings.supabase_url is None or settings.supabase_publishable_key is None:
        return None
    return SupabaseExportFiles(
        client,
        base_url=settings.supabase_url,
        bucket=settings.export_bucket,
        publishable_key=settings.supabase_publishable_key,
        download_seconds=settings.export_download_seconds,
    )
