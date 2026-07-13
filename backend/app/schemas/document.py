from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentCreateText(BaseModel):
    title: str
    text: str = Field(min_length=1)


class DocumentOut(BaseModel):
    id: str
    title: str
    source_type: str
    char_count: int
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
