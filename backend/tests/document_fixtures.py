"""Binary fixture builders shared by the parser and API upload tests.

These construct valid PDF and DOCX bytes in-process so the suite needs no
checked-in binary fixtures and no network - preserving the zero-external-
dependency property described in conftest.py. The DOCX builder emits the
same zip/XML layout Word produces, so it exercises both the python-docx
path and the stdlib fallback path in app/services/parsers.py.

Not a test module: the leading-underscore helper names are kept so pytest
never mistakes them for tests.
"""
from __future__ import annotations

import io
import zipfile


def _build_pdf(pages: list[str | None]) -> bytes:
    """Build a minimal single-font PDF. `None` = a page with no text layer
    (what a scanned/image-only page looks like to a text extractor).
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based object number

    content_ids: list[int] = []
    for text in pages:
        stream = (
            b"BT /F1 12 Tf 72 720 Td (" + text.encode("ascii") + b") Tj ET"
            if text is not None
            else b""
        )
        content_ids.append(
            add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        )

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    # The /Pages node is written after the page objects, so its object number
    # has to be predicted here to fill in each page's /Parent back-reference.
    pages_id = len(objects) + len(pages) + 1

    page_ids: list[int] = []
    for content_id in content_ids:
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
                % (pages_id, content_id, font_id)
            )
        )

    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    assert add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)) == pages_id
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n" % (
        len(objects) + 1,
        catalog_id,
        xref_offset,
    )
    out += b"%%EOF\n"
    return bytes(out)


_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_DOCX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def _build_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal .docx package containing the given paragraphs."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join("<w:p><w:r><w:t>" + p + "</w:t></w:r></w:p>" for p in paragraphs)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<w:document " + ns + "><w:body>" + body + "</w:body></w:document>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", _DOCX_RELS)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
