"""Agent 3: systematizes the collected evidence and verifies each source.

Split into two logical steps (kept in one node here for the demo scaffold;
see README TODO for splitting into agent3a/agent3b once source verification
grows more complex, e.g. to sit behind a human-review interrupt).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas.state import AuditState, FinalReport, SourceVerification

SYSTEM_PROMPT = """You are a document systematization agent for an audit workflow.
Given a task and a set of source documents, produce a concise, well-organized
summary of findings relevant to the task. Do not invent information not
present in the documents.
"""


def _verify_source(doc: dict) -> SourceVerification:
    """Basic provenance check.

    Placeholder heuristic — replace with real checks against SharePoint
    metadata (e.g. last_modified freshness, library permissions, version
    history) once the .NET CSOM sidecar exposes that metadata reliably.
    """
    has_metadata = bool(doc.get("last_modified")) and bool(doc.get("library"))
    return SourceVerification(
        doc_id=doc["doc_id"],
        verified=has_metadata,
        verification_notes=(
            "Metadata present." if has_metadata else "Missing last_modified/library metadata."
        ),
        excluded_from_report=not has_metadata,
    )


async def agent3_systematize_and_verify(
    state: AuditState, llm: BaseChatModel
) -> dict:
    docs = state["sharepoint_docs"]

    verifications = [_verify_source(d) for d in docs]
    included_docs = [
        d for d, v in zip(docs, verifications) if not v.excluded_from_report
    ]

    doc_text = "\n".join(
        f"- [{d['doc_id']}] {d.get('title', 'untitled')}: {d.get('content_snippet', '')}"
        for d in included_docs
    ) or "(no verified documents available)"

    response = await llm.ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"TASK:\n{state['task']}\n\nVERIFIED DOCUMENTS:\n{doc_text}\n\n"
                "Produce a bullet-point list of findings."
            ),
        ]
    )

    partial_evidence = (
        state["sufficiency_verdict"] != "sufficient"
        and state["iteration"] >= state["max_iterations"]
    )

    report = FinalReport(
        task=state["task"],
        summary=response.content,
        findings=[line.strip("- ").strip() for line in response.content.splitlines() if line.strip()],
        partial_evidence=partial_evidence,
        source_count=len(included_docs),
        excluded_source_count=len(docs) - len(included_docs),
    )

    return {
        "source_verification": [v.model_dump() for v in verifications],
        "final_report": report.model_dump(),
        "partial_evidence": partial_evidence,
    }
