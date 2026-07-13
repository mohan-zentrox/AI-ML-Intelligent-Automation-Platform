from __future__ import annotations

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class CitationOut(BaseModel):
    marker: int
    document_id: str
    chunk_id: str
    score: float
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    confidence: float
    refused: bool
    query_log_id: str
    routed_to_review: bool
