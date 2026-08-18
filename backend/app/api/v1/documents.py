"""
Document ingestion endpoints.

Reference: FRD section "Document Ingestion Pipeline". Accepts plain text
(JSON body) or a file upload in any format registered in
app.services.parsers.PARSERS (.txt/.md/.pdf/.docx today); all paths funnel
through app.services.ingestion.ingest_document. OCR of scanned PDFs and
email ingestion remain scaffolded - see app/scaffold/parsers.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.document import DocumentCreateText, DocumentOut
from app.services.ingestion import ingest_document
from app.services.parsers import (
    CorruptDocument,
    MissingParserDependency,
    UnsupportedFormat,
    parse_upload,
)

router = APIRouter(prefix="/documents", tags=["documents"])

_INGEST_ROLES = (Role.ADMIN, Role.WORKFLOW_BUILDER, Role.ANALYST)


def _to_document_out(db: Session, document: Document) -> DocumentOut:
    chunk_count = db.query(func.count(Chunk.id)).filter(Chunk.document_id == document.id).scalar()
    return DocumentOut(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        char_count=document.char_count,
        chunk_count=chunk_count or 0,
        created_at=document.created_at,
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
        raw_bytes = await file.read()
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
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*Role)),
) -> list[DocumentOut]:
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    return [_to_document_out(db, d) for d in documents]
