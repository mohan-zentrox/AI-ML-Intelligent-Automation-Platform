"""
SCAFFOLD ONLY - Remaining multi-format ingestion paths.

Reference: FRD section 4.2 "Multi-Format Document Ingestion" and
SRS section 5.1 "Supported Input Formats".

IMPLEMENTED AND MOVED OUT OF SCAFFOLD:
  - FRD 4.2.1 PDF ingestion  -> app.services.parsers.parse_pdf
  - FRD 4.2.3 DOCX ingestion -> app.services.parsers.parse_docx
Both are wired into `POST /api/v1/documents` via
`app.services.parsers.parse_upload`, and register themselves in the
`PARSERS` extension table there.

What is left below is still intentionally unimplemented. Each should
ultimately return plain text (plus any extracted structural metadata) and
hand off to `app.services.ingestion.ingest_document`, so no changes to
chunking, embedding, or vector storage are needed once implemented - and
each should be registered in `app.services.parsers.PARSERS` so the API
picks it up with no router changes.
"""
from __future__ import annotations


def parse_scanned_pdf_via_ocr(file_bytes: bytes) -> str:
    """TODO(FRD 4.2.2 - OCR ingestion): OCR a scanned/image-only PDF or image.

    `app.services.parsers.parse_pdf` already reports which pages carry no
    text layer via `ParsedDocument.metadata["empty_pages"]`; that list is the
    intended trigger for routing a document (or individual pages) here.

    Suggested approach: pytesseract/Tesseract or a hosted OCR API behind the
    same pluggable-provider pattern used for LLMProvider, so OCR engines are
    swappable too.
    """
    raise NotImplementedError("OCR ingestion is scaffolded - see FRD 4.2.2")


def parse_email(raw_email_bytes: bytes) -> tuple[str, dict]:
    """TODO(FRD 4.2.4 - Email ingestion): parse a .eml/.msg message.

    Should return (body_text, metadata) where metadata includes sender,
    recipients, subject, timestamp, and attachment references (attachments
    should recurse into app.services.parsers.parse_upload, which already
    dispatches PDF/DOCX/text by extension).
    """
    raise NotImplementedError("Email ingestion is scaffolded - see FRD 4.2.4")
