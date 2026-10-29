"""Structured outputs for model nodes. Length limits are part of the contract."""
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "order_dependent",
    "async_race",
    "time_dependent",
    "randomness",
    "shared_resource",
    "hash_order",
    "environment",
    "unknown",
]


class ClassifyOut(BaseModel):
    category: Category
    rationale: str = Field(max_length=300)
    confidence: float = Field(ge=0, le=1)


class SearchQueryOut(BaseModel):
    query: str = Field(max_length=120)
    library: str | None = Field(default=None, max_length=60)


class DiagnoseOut(BaseModel):
    root_cause: str = Field(max_length=800)
    mechanism: str = Field(max_length=800)
    culprit: str = Field(max_length=300)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    category: Category
    fix_strategy: str = Field(max_length=400)
    needs_human: bool
    confidence: float = Field(ge=0, le=1)


class ReferenceMatchOut(BaseModel):
    matched_urls: list[str] = Field(default_factory=list, max_length=8)


class PatchOut(BaseModel):
    # One unified-diff line per item. A single string drops the newlines.
    lines: list[str] = Field(min_length=1, max_length=400)
    summary: str = Field(max_length=300)
