"""
Document ingestion endpoints.

Reference: FRD section "Document Ingestion Pipeline". Accepts plain text
(JSON body) or a .txt/.md file upload; both funnel through
app.services.ingestion.ingest_document. PDF/DOCX/OCR/email ingestion are
scaffolded (not implemented) - see app/scaffold/parsers.py.
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

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_UPLOAD_SUFFIXES = (".txt", ".md")

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
        if not file.filename or not file.filename.lower().endswith(_ALLOWED_UPLOAD_SUFFIXES):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Only .txt/.md uploads are supported today. PDF/DOCX/OCR "
                    "ingestion are scaffolded - see app/scaffold/parsers.py."
                ),
            )
        raw_bytes = await file.read()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        doc_title = title or file.filename
        source_type = file.filename.rsplit(".", 1)[-1].lower()
    elif text is not None:
        if not title:
            raise HTTPException(status_code=400, detail="`title` is required for text ingestion")
        raw_text = text
        doc_title = title
        source_type = "text"
    else:
        raise HTTPException(status_code=400, detail="Provide either `text` (+ `title`) or `file`")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Document content is empty")

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
