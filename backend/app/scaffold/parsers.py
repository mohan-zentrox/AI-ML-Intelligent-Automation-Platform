"""
SCAFFOLD ONLY - Multi-format document parsing.

Reference: FRD section 4.2 "Multi-Format Document Ingestion" and
SRS section 5.1 "Supported Input Formats".

Today `POST /api/v1/documents` only accepts plain text and .txt/.md
uploads (see app/api/v1/documents.py + app/services/ingestion.py). The
functions below are the intended extension points for the remaining
formats called out in the FRD. Each should ultimately return plain text
(plus any extracted structural metadata) and hand off to
`app.services.ingestion.ingest_document`, so no changes to chunking,
embedding, or vector storage are needed once these are implemented.

None of this module is wired into the API yet - it is intentionally
unimplemented scaffolding.
"""
from __future__ import annotations


def parse_pdf(file_bytes: bytes) -> str:
    """TODO(FRD 4.2.1 - PDF ingestion): extract text from a PDF.

    Suggested approach: PyMuPDF (fitz) or pdfplumber for text-layer PDFs;
    fall back to `parse_scanned_pdf_via_ocr` for image-only pages.
    """
    raise NotImplementedError("PDF ingestion is scaffolded - see FRD 4.2.1")


def parse_scanned_pdf_via_ocr(file_bytes: bytes) -> str:
    """TODO(FRD 4.2.2 - OCR ingestion): OCR a scanned/image-only PDF or image.

    Suggested approach: pytesseract/Tesseract or a hosted OCR API behind the
    same pluggable-provider pattern used for LLMProvider, so OCR engines are
    swappable too.
    """
    raise NotImplementedError("OCR ingestion is scaffolded - see FRD 4.2.2")


def parse_docx(file_bytes: bytes) -> str:
    """TODO(FRD 4.2.3 - DOCX ingestion): extract text from a Word document.

    Suggested approach: python-docx, preserving heading structure as
    metadata for downstream document classification (see classification.py).
    """
    raise NotImplementedError("DOCX ingestion is scaffolded - see FRD 4.2.3")


def parse_email(raw_email_bytes: bytes) -> tuple[str, dict]:
    """TODO(FRD 4.2.4 - Email ingestion): parse a .eml/.msg message.

    Should return (body_text, metadata) where metadata includes sender,
    recipients, subject, timestamp, and attachment references (attachments
    should recurse into the other parse_* functions here).
    """
    raise NotImplementedError("Email ingestion is scaffolded - see FRD 4.2.4")
