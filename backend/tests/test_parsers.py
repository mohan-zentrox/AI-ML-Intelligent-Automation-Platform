"""Multi-format parsing tests (FRD 4.2).

PDF/DOCX inputs come from tests/document_fixtures.py, which builds them
in-process - no checked-in binaries, no network.
"""
from __future__ import annotations

import pytest

from app.services import parsers
from app.services.parsers import (
    CorruptDocument,
    UnsupportedFormat,
    parse_docx,
    parse_pdf,
    parse_text,
    parse_upload,
)
from tests.document_fixtures import _build_docx, _build_pdf

# --- plain text -------------------------------------------------------


def test_parse_text_normalizes_line_endings_and_blank_runs():
    parsed = parse_text(b"first line\r\n\r\n\r\n\r\nsecond line\r\n")
    assert parsed.text == "first line\n\nsecond line"
    assert parsed.source_type == "text"


def test_parse_text_replaces_invalid_utf8_instead_of_failing():
    # Matches the pre-existing endpoint behaviour: degrade the byte, keep the doc.
    parsed = parse_text(b"caf\xe9 policy")
    assert "policy" in parsed.text


# --- PDF (FRD 4.2.1) --------------------------------------------------


def test_parse_pdf_extracts_text_from_every_page():
    parsed = parse_pdf(_build_pdf(["Invoice total is 4200 USD", "Payment terms are net 30"]))
    assert "Invoice total is 4200 USD" in parsed.text
    assert "Payment terms are net 30" in parsed.text
    assert parsed.source_type == "pdf"
    assert parsed.metadata["page_count"] == 2
    assert parsed.metadata["empty_pages"] == []


def test_parse_pdf_reports_pages_with_no_text_layer():
    """Image-only pages are the OCR hand-off signal (FRD 4.2.2), so they must
    be reported rather than silently dropped."""
    parsed = parse_pdf(_build_pdf(["Page one has text", None, "Page three has text"]))
    assert parsed.metadata["empty_pages"] == [2]
    assert parsed.metadata["page_count"] == 3


def test_parse_pdf_rejects_garbage_bytes_as_corrupt():
    with pytest.raises(CorruptDocument):
        parse_pdf(b"this is definitely not a pdf")


# --- DOCX (FRD 4.2.3) -------------------------------------------------


def test_parse_docx_extracts_paragraphs():
    parsed = parse_docx(_build_docx(["Master Services Agreement", "Effective 2026-01-01."]))
    assert "Master Services Agreement" in parsed.text
    assert "Effective 2026-01-01." in parsed.text
    assert parsed.source_type == "docx"


def test_stdlib_docx_fallback_matches_python_docx_output(monkeypatch):
    """The zero-dependency fallback must produce the same text as python-docx,
    otherwise ingestion quality would silently depend on install state."""
    docx_bytes = _build_docx(["Section one body.", "Section two body."])
    with_library = parse_docx(docx_bytes)

    real_import = __import__

    def _no_python_docx(name, *args, **kwargs):
        if name == "docx":
            raise ImportError("simulated: python-docx not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_python_docx)
    without_library = parse_docx(docx_bytes)

    assert without_library.metadata["parser"] == "stdlib"
    assert without_library.text == with_library.text


def test_parse_docx_rejects_non_zip_payload():
    with pytest.raises(CorruptDocument):
        parse_docx(b"not a zip archive at all")


# --- dispatch ---------------------------------------------------------


@pytest.mark.parametrize("filename", ["report.PDF", "report.pdf"])
def test_parse_upload_dispatch_is_case_insensitive(filename):
    parsed = parse_upload(filename, _build_pdf(["Quarterly summary"]))
    assert "Quarterly summary" in parsed.text


def test_parse_upload_routes_markdown_to_the_text_parser():
    parsed = parse_upload("notes.md", b"# Heading\n\nBody text.")
    assert parsed.source_type == "text"
    assert "Body text." in parsed.text


def test_parse_upload_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFormat):
        parse_upload("archive.zip", b"PK\x03\x04")


def test_parse_upload_gives_legacy_doc_an_actionable_message():
    with pytest.raises(UnsupportedFormat, match="re-save the file as .docx"):
        parse_upload("contract.doc", b"\xd0\xcf\x11\xe0")


def test_parse_upload_rejects_extensionless_filename():
    with pytest.raises(UnsupportedFormat):
        parse_upload("README", b"content")


def test_every_registered_suffix_is_advertised_as_supported():
    """Guards the API's 415 message against drifting from the real registry."""
    assert set(parsers.SUPPORTED_SUFFIXES) == set(parsers.PARSERS)
    assert {".txt", ".md", ".pdf", ".docx"} <= set(parsers.PARSERS)
