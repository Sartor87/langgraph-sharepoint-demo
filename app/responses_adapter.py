"""Maps AuditState onto the Foundry Responses protocol's input/output shape.

AuditState (app/schemas/state.py) has no `messages` field, unlike the
chat-shaped graphs langchain_azure_ai.agents.hosting's default hosts expect.
These are the pure, independently-testable pieces of that mapping; the
protocol-facing glue (which hook of ResponsesHostServer to override, and how
to emit its response events) lives alongside these functions once Task 6
determines the installed package's real API — see that task for why it
isn't decided here.
"""

from __future__ import annotations

from app.schemas.state import AuditState


def extract_task_text(input_data) -> str:
    """Turn a Responses `input` field into plain task text for `initial_state()`.

    `input_data` is either a plain string, or a list of message-like dicts
    (OpenAI Responses API shape) — this returns the most recent user
    message's text.
    """
    if isinstance(input_data, str):
        return input_data

    for item in reversed(input_data):
        role = item.get("role") if isinstance(item, dict) else None
        if role != "user":
            continue

        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in ("input_text", "text")
            ]
            if parts:
                return "\n".join(parts)

    raise ValueError(f"Could not extract task text from Responses input: {input_data!r}")


def build_output_text(state: AuditState) -> str:
    """Turn a finished AuditState into the Responses output text.

    `final_report` and `source_verification`/`verdict_history` entries are
    dicts produced by `FinalReport.model_dump()` / `SufficiencyVerdict.model_dump()`
    / `SourceVerification.model_dump()` (see app/schemas/state.py), not plain
    strings — this renders their real fields into readable text.
    """
    final_report = state.get("final_report")

    if final_report is None:
        lines = ["(no report produced)"]
        partial_evidence = state.get("partial_evidence")
    else:
        lines = [final_report["summary"]]
        findings = final_report.get("findings") or []
        if findings:
            lines.append("")
            lines.extend(f"- {finding}" for finding in findings)
        # agent3_finalize (app/nodes/agent3_finalize.py) computes
        # partial_evidence and writes it onto both final_report and the
        # top-level AuditState field in the same update, so the two always
        # agree; final_report's copy is preferred here since it's the one
        # actually attached to the report being rendered.
        partial_evidence = final_report["partial_evidence"]

    if partial_evidence:
        lines.insert(
            0,
            "NOTE: this result is partial — the retry budget was exhausted "
            "before evidence was judged sufficient.\n",
        )

    verdict_history = state.get("verdict_history") or []
    if verdict_history:
        lines.append("\n---\nSufficiency verdicts:")
        for i, verdict in enumerate(verdict_history, start=1):
            lines.append(
                f"{i}. {verdict['decision']} "
                f"(confidence: {verdict['confidence']:.2f}) — {verdict['reasoning']}"
            )

    source_verification = state.get("source_verification") or []
    if source_verification:
        lines.append("\n---\nSource verification:")
        for source in source_verification:
            status = "verified" if source["verified"] else "NOT verified"
            lines.append(f"- {source['doc_id']}: {status} — {source['verification_notes']}")

    return "\n".join(lines)
