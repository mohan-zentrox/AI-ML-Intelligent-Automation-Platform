"""Chunking correctness tests - app/services/chunking.py."""
from __future__ import annotations

import pytest

from app.services.chunking import chunk_text


def _words(n: int) -> str:
    return " ".join(f"tok{i}" for i in range(n))


def test_chunk_text_overlap_is_correct():
    text = _words(10)  # tok0 .. tok9
    chunks = chunk_text(text, chunk_size_tokens=5, overlap_tokens=2)

    assert len(chunks) == 3
    assert [c.token_count for c in chunks] == [5, 5, 4]
    assert chunks[0].text.split() == [f"tok{i}" for i in range(0, 5)]
    assert chunks[1].text.split() == [f"tok{i}" for i in range(3, 8)]
    assert chunks[2].text.split() == [f"tok{i}" for i in range(6, 10)]

    # Overlap between consecutive chunks is exactly overlap_tokens words.
    overlap_01 = set(chunks[0].text.split()) & set(chunks[1].text.split())
    overlap_12 = set(chunks[1].text.split()) & set(chunks[2].text.split())
    assert len(overlap_01) == 2
    assert len(overlap_12) == 2


def test_chunk_text_short_text_returns_single_chunk():
    text = _words(3)
    chunks = chunk_text(text, chunk_size_tokens=200, overlap_tokens=40)
    assert len(chunks) == 1
    assert chunks[0].token_count == 3
    assert chunks[0].text.split() == ["tok0", "tok1", "tok2"]


def test_chunk_text_empty_text_returns_no_chunks():
    assert chunk_text("", chunk_size_tokens=10, overlap_tokens=2) == []
    assert chunk_text("   \n  ", chunk_size_tokens=10, overlap_tokens=2) == []


def test_chunk_text_indices_are_sequential():
    chunks = chunk_text(_words(30), chunk_size_tokens=10, overlap_tokens=3)
    assert [c.index for c in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize(
    "chunk_size,overlap",
    [(0, 0), (-5, 0), (10, 10), (10, 15), (10, -1)],
)
def test_chunk_text_rejects_invalid_params(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text(_words(20), chunk_size_tokens=chunk_size, overlap_tokens=overlap)


def test_chunk_text_default_project_settings_cover_a_real_document():
    # Sanity check using the platform defaults (200/40) against a longer,
    # realistic document to make sure nothing loops forever or drops text.
    paragraph = (
        "Project Synapse ingests documents, splits them into overlapping "
        "chunks, embeds each chunk, and stores the vectors for retrieval. "
    ) * 20
    chunks = chunk_text(paragraph, chunk_size_tokens=200, overlap_tokens=40)
    assert len(chunks) >= 1
    # Every original word appears in at least one chunk (no data loss).
    all_chunk_words = set()
    for c in chunks:
        all_chunk_words.update(c.text.split())
    assert set(paragraph.split()) <= all_chunk_words
