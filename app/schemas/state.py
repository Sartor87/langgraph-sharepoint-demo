"""
State schema for the SharePoint audit graph.

- AuditState: the LangGraph shared state (TypedDict).
- SufficiencyVerdict: Agent 2's structured output, produced via
  llm.with_structured_output(SufficiencyVerdict) — never parsed from free text.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator


class InsufficiencyReason(str, Enum):
    NO_RELEVANT_DOCS = "no_relevant_docs"
    PARTIAL_COVERAGE = "partial_coverage"
    OUTDATED_VERSION = "outdated_version"
    CONFLICTING_SOURCES = "conflicting_sources"
    MISSING_METADATA = "missing_metadata"


class DocumentAssessment(BaseModel):
    """Per-document relevance assessment, for audit granularity."""

    doc_id: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    covers_task_aspect: str = Field(
        description="Which specific aspect of the task this document covers."
    )


class SufficiencyVerdict(BaseModel):
    """Structured output for Agent 2 (sufficiency evaluation)."""

    decision: Literal["sufficient", "insufficient"]
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the decision.")
    reasoning: str = Field(description="Short, defensible explanation for the audit log.")

    insufficiency_reasons: list[InsufficiencyReason] = Field(default_factory=list)
    refined_query: str | None = Field(
        default=None,
        description="A more precise search query, required when decision=insufficient.",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Which specific aspects of the task are not yet covered.",
    )

    document_assessments: list[DocumentAssessment] = Field(default_factory=list)

    requires_human_review: bool = Field(
        default=False,
        description="True if confidence is below threshold or sources conflict.",
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> "SufficiencyVerdict":
        if self.decision == "insufficient" and not self.refined_query:
            raise ValueError("refined_query is required when decision=insufficient")
        if self.decision == "sufficient" and self.insufficiency_reasons:
            raise ValueError(
                "insufficiency_reasons must be empty when decision=sufficient"
            )
        if InsufficiencyReason.CONFLICTING_SOURCES in self.insufficiency_reasons:
            # Force override — don't rely on the model to set this consistently.
            self.requires_human_review = True
        return self


class SourceVerification(BaseModel):
    """Agent 3's per-source provenance/trust check."""

    doc_id: str
    verified: bool
    verification_notes: str
    excluded_from_report: bool = False


class FinalReport(BaseModel):
    task: str
    summary: str
    findings: list[str]
    partial_evidence: bool = Field(
        default=False,
        description="True if MAX_ITERATIONS was hit before sufficiency was reached.",
    )
    source_count: int
    excluded_source_count: int


def _append(existing: list, new: list) -> list:
    """Reducer: append-only merge for audit trail lists."""
    return existing + new


class AuditState(TypedDict):
    # Input
    task: str

    # Search loop
    query: str
    sharepoint_docs: list[dict]
    iteration: int
    max_iterations: int

    # Agent 2 output
    sufficiency_verdict: Literal["sufficient", "insufficient"] | None
    requires_human_review: bool
    verdict_history: Annotated[list[dict], _append]

    # Agent 4 output (Fabric MCP context, gathered in parallel with Agent 1)
    fabric_context: Annotated[list[dict], _append]

    # Agent 3 output
    source_verification: list[dict]
    final_report: dict | None
    partial_evidence: bool
