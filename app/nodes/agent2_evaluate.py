"""Agent 2: evaluates whether retrieved documents are sufficient for the task.

Uses structured output (SufficiencyVerdict) instead of free-text parsing, so
the routing decision downstream is deterministic and type-safe.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas.state import AuditState, SufficiencyVerdict

SYSTEM_PROMPT = """You are a document-sufficiency evaluator for an audit workflow.
Given a task and a set of retrieved SharePoint documents, decide whether the
documents are SUFFICIENT to complete the task, or INSUFFICIENT.

If insufficient:
- Explain which aspects of the task are not yet covered.
- Propose a refined search query that would help close the gap.
- Flag conflicting sources or missing metadata explicitly.

Be conservative: prefer "insufficient" when in doubt, unless the iteration
budget is nearly exhausted.
"""


def _build_evaluation_prompt(task: str, docs: list[dict]) -> str:
    doc_summaries = "\n".join(
        f"- [{d['doc_id']}] {d.get('title', 'untitled')}: "
        f"{d.get('content_snippet', '')[:300]}"
        for d in docs
    ) or "(no documents retrieved yet)"

    return (
        f"TASK:\n{task}\n\n"
        f"RETRIEVED DOCUMENTS ({len(docs)}):\n{doc_summaries}\n\n"
        "Evaluate sufficiency and respond with the structured verdict."
    )


async def agent2_evaluate_sufficiency(
    state: AuditState, llm: BaseChatModel
) -> dict:
    structured_llm = llm.with_structured_output(SufficiencyVerdict)

    verdict: SufficiencyVerdict = await structured_llm.ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=_build_evaluation_prompt(state["task"], state["sharepoint_docs"])
            ),
        ]
    )

    next_query = (
        verdict.refined_query if verdict.decision == "insufficient" else state["query"]
    )

    return {
        "sufficiency_verdict": verdict.decision,
        "requires_human_review": verdict.requires_human_review,
        "query": next_query,
        "verdict_history": [verdict.model_dump()],
    }
