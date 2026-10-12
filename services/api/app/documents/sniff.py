"""What an uploaded file really is, decided from its bytes and never from what the browser says.

A file name and a ``Content-Type`` header are claims by the sender. The type of a file is decided
here from its *signature* (the first bytes) and, for text, from the content itself; the name is
then only checked for consistency, so a program renamed ``notes.pdf`` or a PDF renamed ``notes.txt``
is refused instead of being trusted. Nothing here opens, renders or executes a file.
"""

import re
from dataclasses import dataclass
from typing import Literal

DocumentKind = Literal["pdf", "text", "image"]

# Extensions we accept for each kind (lower case, no dot). A file with no extension is only
# accepted as text.
_EXTENSIONS: dict[DocumentKind, frozenset[str]] = {
    "pdf": frozenset({"pdf"}),
    "text": frozenset({"txt", "text", "md", "markdown"}),
    "image": frozenset({"png", "jpg", "jpeg", "webp"}),
}

_PNG = b"\x89PNG\r\n\x1a\n"
_MAX_PDF_HEADER_OFFSET = 1024
# More than this share of control characters means a binary file, however it decodes.
_MAX_CONTROL_SHARE = 0.02
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

SUPPORTED_TEXT = "PDF, plain text (.txt, .md) or an image (.png, .jpg, .webp)"


class UnsupportedFile(Exception):
    """The file is not one we accept. ``code`` is stable; ``message`` is safe to show a learner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Detected:
    kind: DocumentKind
    # The type we store and send on: decided here, never copied from the request.
    mime_type: str
    extension: str


def _extension(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[1].lower() if "." in name.strip(".") else ""


def detect(data: bytes, filename: str) -> Detected:
    """The type of ``data``, or ``UnsupportedFile`` saying why it cannot be used."""
    if not data:
        raise UnsupportedFile("FILE_EMPTY", "That file is empty.")
    extension = _extension(filename)

    kind: DocumentKind
    mime: str
    head = data[:_MAX_PDF_HEADER_OFFSET]
    if b"%PDF-" in head:
        kind, mime = "pdf", "application/pdf"
    elif data.startswith(_PNG):
        kind, mime = "image", "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        kind, mime = "image", "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind, mime = "image", "image/webp"
    elif _looks_like_text(data):
        kind, mime = "text", "text/plain"
    else:
        raise UnsupportedFile(
            "FILE_TYPE_UNSUPPORTED",
            f"This kind of file can't be used. Upload a {SUPPORTED_TEXT}, or paste the text.",
        )

    allowed = _EXTENSIONS[kind]
    if extension and extension not in allowed:
        raise UnsupportedFile(
            "FILE_TYPE_MISMATCH",
            f"The file name ends in .{extension} but its content is {_describe(kind)}. "
            "Check that you chose the right file.",
        )
    if not extension and kind != "text":
        raise UnsupportedFile(
            "FILE_TYPE_MISMATCH",
            f"The file has no extension but its content is {_describe(kind)}. "
            "Give it the right extension.",
        )
    return Detected(kind=kind, mime_type=mime, extension=extension or "txt")


def _describe(kind: DocumentKind) -> str:
    return {"pdf": "a PDF", "text": "plain text", "image": "an image"}[kind]


def decode_text(data: bytes) -> str | None:
    """``data`` as text if it is UTF-8 (with or without a BOM) or UTF-16 with a BOM, else None."""
    for encoding in _encodings(data):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _encodings(data: bytes) -> tuple[str, ...]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ("utf-16",)
    return ("utf-8-sig",)


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    text = decode_text(data)
    if text is None or not text.strip():
        return False
    controls = len(_CONTROL.findall(text))
    return controls / max(1, len(text)) <= _MAX_CONTROL_SHARE


def safe_file_name(filename: str, fallback_extension: str) -> str:
    """A name that is safe in a storage path and on a download header: letters, digits, ``._-``."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip().lstrip(".")
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, fallback_extension
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:60] or "document"
    extension = re.sub(r"[^A-Za-z0-9]+", "", extension).lower()[:5] or fallback_extension
    return f"{stem}.{extension}"
