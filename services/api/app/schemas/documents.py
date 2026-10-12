"""Request and response contracts for study documents: uploads, extracted pages and search.

Nothing here carries a file's bytes back to the browser except through the download route, a
storage path or a signed link: the API shows what a document *is* (status, warnings, previews of
the text taken from it) and never where it is stored.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.jobs import GenerationJob

DocumentKind = Literal["pdf", "text", "image", "pasted"]
DocumentStatus = Literal["queued", "processing", "review", "ready", "failed"]
PageSource = Literal["text_layer", "ocr", "text"]
Legibility = Literal["clear", "partly", "poor", "none"]

DocumentTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]

MAX_PASTED_CHARS = 1_000_000
MAX_PAGE_CHARS = 400_000
MAX_SEARCH_CHARS = 500


class DocumentWarning(BaseModel):
    """Something worth knowing about how a document was read (never file content)."""

    code: str
    message: str
    page: int | None = None


class Document(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    title: str
    kind: DocumentKind
    original_name: str | None
    size_bytes: int
    status: DocumentStatus
    # Set when status is `failed`: a stable code and a sentence a learner can read.
    error_code: str | None
    error_message: str | None
    # True for real pages (a PDF or a picture); False when "pages" are parts of a text.
    paginated: bool
    page_count: int | None
    chunk_count: int
    char_count: int
    # How many pages were read from a picture by a vision model, which the learner should check.
    ocr_page_count: int
    warnings: list[DocumentWarning]
    embedding_model: str | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # The newest processing job (to show progress); None only if it was never queued.
    job: GenerationJob | None = None
    # Whether pages still need the learner's attention before the document can be used.
    needs_review: bool = False


class DocumentLimits(BaseModel):
    max_bytes: int
    max_pages: int
    max_ocr_pages: int
    documents_per_goal: int
    accepted: list[str]


class DocumentList(BaseModel):
    items: list[Document]
    limits: DocumentLimits
    goal_archived: bool
    # False when this server has no file storage configured: uploads would be refused (503).
    storage_available: bool
    # Whether scanned pages and pictures can be read here (needs an AI provider).
    ocr_available: bool
    # Whether the material can be indexed here (needs an embedding provider).
    indexing_available: bool


class PastedMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: DocumentTitle
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PASTED_CHARS)]


class DocumentRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: DocumentTitle


class DocumentPage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str
    source: PageSource
    # Only for pages read from a picture: how sure the model was.
    legibility: Legibility | None
    # True until the learner has looked at (or corrected) an uncertain reading.
    needs_review: bool
    edited: bool


class DocumentPages(BaseModel):
    items: list[DocumentPage]
    total: int
    offset: int
    limit: int
    # Whether the learner can correct text right now (only while the document waits for review).
    editable: bool


class PageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(max_length=MAX_PAGE_CHARS)]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=MAX_SEARCH_CHARS)
    ]
    # Limit the search to these documents of the goal; omitted means all its ready documents.
    document_ids: Annotated[list[UUID], Field(max_length=50)] | None = None
    limit: Annotated[int, Field(ge=1, le=20)] | None = None


class PassageHit(BaseModel):
    """One passage that was really retrieved. These identifiers are what a citation points at."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    page_start: int
    page_end: int
    # "p. 3", "pp. 3 to 4" or "part 2": ready to show beside the passage.
    position: str
    section_title: str | None
    content: str
    # Cosine similarity of the passage and the question, 0 to 1.
    similarity: float
    # Whether the passage also contains words from the question.
    keyword_match: bool


class SearchResult(BaseModel):
    items: list[PassageHit]
    # False when nothing in the learner's material matched well enough: say so, don't guess.
    enough_evidence: bool
    searched_documents: int
