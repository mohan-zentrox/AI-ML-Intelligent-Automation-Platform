"""
Document ingestion endpoints.

Reference: FRD section "Document Ingestion Pipeline". Accepts plain text
(JSON body) or a file upload in any format registered in
app.services.parsers.PARSERS (.txt/.md/.pdf/.docx today); all paths funnel
through app.services.ingestion.ingest_document. OCR of scanned PDFs and
email ingestion remain scaffolded - see app/scaffold/parsers.py.

Also serves the document taxonomy and re-classification (FRD 7) - see
app/services/classification.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.document import CategoryOut, DocumentCreateText, DocumentOut, TaxonomyOut
from app.services.classification import TAXONOMY, TAXONOMY_VERSION
from app.services.ingestion import classify_and_route, ingest_document
from app.services.parsers import (
    CorruptDocument,
    MissingParserDependency,
    UnsupportedFormat,
    parse_upload,
)

router = APIRouter(prefix="/documents", tags=["documents"])

settings = get_settings()

# Read granularity for the size-capped upload read below. Small enough that an
# oversized file is rejected after buffering ~1 MB rather than all of it.
_UPLOAD_CHUNK_BYTES = 1024 * 1024

_INGEST_ROLES = (Role.ADMIN, Role.WORKFLOW_BUILDER, Role.ANALYST)
# Re-running the classifier costs a provider call and overwrites a label a
# reviewer may already have confirmed, so it is not open to Analysts.
_RECLASSIFY_ROLES = (Role.ADMIN, Role.WORKFLOW_BUILDER)


def _human_size(num_bytes: int) -> str:
    """Render a byte count for an error message a human has to act on.

    Integer-dividing straight to MB reports a 512 KB cap as "0 MB", which
    tells the caller nothing about what size would actually be accepted.
    """
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.10g} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.10g} KB"
    return f"{num_bytes} bytes"


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload, refusing anything over `max_bytes` with a 413.

    Reads in chunks and aborts mid-stream on purpose. The obvious spelling -
    `await file.read()` and then check `len()` - allocates the entire body
    before it can decide to reject it, so the oversized upload it is meant to
    defend against has already done its damage by the time the check runs.

    Content-Length is deliberately not trusted as the gate: it is client-
    supplied, absent under chunked transfer encoding, and describes the whole
    multipart envelope rather than this part. The bytes actually read are the
    only honest measure.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the maximum upload size of {_human_size(max_bytes)}.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _to_document_out(db: Session, document: Document) -> DocumentOut:
    chunk_count = db.query(func.count(Chunk.id)).filter(Chunk.document_id == document.id).scalar()
    return DocumentOut(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        char_count=document.char_count,
        chunk_count=chunk_count or 0,
        created_at=document.created_at,
        classification_label=document.classification_label,
        classification_confidence=document.classification_confidence,
        classification_status=document.classification_status,
        taxonomy_version=document.taxonomy_version,
        classified_at=document.classified_at,
    )


@router.post("", response_model=DocumentOut)
async def create_document(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_INGEST_ROLES)),
    title: str | None = Form(default=None),
    text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> DocumentOut:
    if file is not None:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Uploaded file has no filename")
        raw_bytes = await _read_upload_capped(file, settings.MAX_UPLOAD_BYTES)
        try:
            parsed = parse_upload(file.filename, raw_bytes)
        except UnsupportedFormat as exc:
            # 415 rather than 400: the request is well-formed, the media type isn't.
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except MissingParserDependency as exc:
            # A deployment gap, not a client error - the format is supported
            # but this install is missing its optional package.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CorruptDocument as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        raw_text = parsed.text
        doc_title = title or file.filename
        source_type = parsed.source_type
    elif text is not None:
        if not title:
            raise HTTPException(status_code=400, detail="`title` is required for text ingestion")
        raw_text = text
        doc_title = title
        source_type = "text"
    else:
        raise HTTPException(status_code=400, detail="Provide either `text` (+ `title`) or `file`")

    if not raw_text.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Document content is empty. Scanned/image-only PDFs have no text "
                "layer and need OCR, which is not implemented yet (FRD 4.2.2)."
            ),
        )

    document = ingest_document(
        db,
        title=doc_title,
        raw_text=raw_text,
        source_type=source_type,
        uploaded_by=principal.user_id,
    )
    return _to_document_out(db, document)


@router.post("/text", response_model=DocumentOut)
def create_document_json(
    payload: DocumentCreateText,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_INGEST_ROLES)),
) -> DocumentOut:
    """JSON convenience alias for `POST /documents` with a plain-text body."""
    document = ingest_document(
        db,
        title=payload.title,
        raw_text=payload.text,
        source_type="text",
        uploaded_by=principal.user_id,
    )
    return _to_document_out(db, document)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    label: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*Role)),
) -> list[DocumentOut]:
    """List ingested documents, newest first.

    `label` filters by classification (FRD 7), which is what makes the
    taxonomy useful for routing rather than decorative. Unknown labels 400
    rather than silently returning an empty list, so a typo is obvious.
    """
    query = db.query(Document)
    if label is not None:
        if label not in TAXONOMY:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown label '{label}'. Known labels: {sorted(TAXONOMY)}",
            )
        query = query.filter(Document.classification_label == label)
    documents = query.order_by(Document.created_at.desc()).all()
    return [_to_document_out(db, d) for d in documents]


@router.get("/taxonomy", response_model=TaxonomyOut)
def get_taxonomy(
    principal: Principal = Depends(require_role(*Role)),
) -> TaxonomyOut:
    """The active document taxonomy (FRD 7.1).

    Served rather than duplicated client-side so label pickers and the
    review UI cannot drift out of sync with the backend's label set.
    """
    return TaxonomyOut(
        version=TAXONOMY_VERSION,
        categories=[
            CategoryOut(label=c.label, description=c.description) for c in TAXONOMY.values()
        ],
    )


@router.post("/{document_id}/reclassify", response_model=DocumentOut)
def reclassify_document(
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_RECLASSIFY_ROLES)),
) -> DocumentOut:
    """Re-run classification for one document (FRD 7.1).

    The path for documents ingested under a superseded `taxonomy_version`, or
    whose label a reviewer rejected. Goes through the same
    `classify_and_route` used at ingest time, so the outcome - including a
    fresh review item when confidence is low - is identical to a first-time
    classification.
    """
    document = db.query(Document).filter_by(id=document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.raw_text.strip():
        raise HTTPException(
            status_code=400, detail="Document has no text to classify."
        )

    classify_and_route(db, document, actor_id=principal.user_id)
    return _to_document_out(db, document)
