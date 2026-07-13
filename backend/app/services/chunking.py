"""
Document chunking.

Reference: FRD section "Document Chunking Strategy" - fixed-size token
window with overlap, so that context spanning a window boundary is not lost
between two neighbouring chunks.

We approximate "tokens" with a lightweight whitespace/word tokenizer rather
than pulling in a real tokenizer (tiktoken etc.) to keep the mock/offline
path dependency-free; swapping in a real tokenizer is a one-line change
inside `_tokenize` if/when a specific model's exact token accounting is
required (e.g. for tight context-window budgeting with a real provider).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"\S+")


@dataclass
class Chunk:
    index: int
    text: str
    token_count: int
    start_token: int
    end_token: int


def _tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Return (token, start_char, end_char) for each whitespace-delimited token."""
    return [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def chunk_text(
    text: str,
    *,
    chunk_size_tokens: int = 200,
    overlap_tokens: int = 40,
) -> list[Chunk]:
    """Split `text` into overlapping chunks of ~`chunk_size_tokens` tokens.

    Raises ValueError for nonsensical parameters (overlap >= size would loop
    forever / never advance).
    """
    if chunk_size_tokens <= 0:
        raise ValueError("chunk_size_tokens must be > 0")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be >= 0")
    if overlap_tokens >= chunk_size_tokens:
        raise ValueError("overlap_tokens must be smaller than chunk_size_tokens")

    tokens = _tokenize_with_spans(text)
    if not tokens:
        return []

    stride = chunk_size_tokens - overlap_tokens
    chunks: list[Chunk] = []
    idx = 0
    pos = 0
    n = len(tokens)
    while pos < n:
        window = tokens[pos : pos + chunk_size_tokens]
        if not window:
            break
        start_char = window[0][1]
        end_char = window[-1][2]
        chunk_str = text[start_char:end_char]
        chunks.append(
            Chunk(
                index=idx,
                text=chunk_str,
                token_count=len(window),
                start_token=pos,
                end_token=pos + len(window),
            )
        )
        idx += 1
        if pos + chunk_size_tokens >= n:
            break
        pos += stride
    return chunks
