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
    """Turn a finished AuditState into the Responses output text."""
    report = state.get("final_report") or "(no report produced)"
    lines = [report]

    if state.get("partial_evidence"):
        lines.insert(
            0,
            "NOTE: this result is partial — the retry budget was exhausted "
            "before evidence was judged sufficient.\n",
        )

    verdict_history = state.get("verdict_history") or []
    if verdict_history:
        lines.append("\n---\nSufficiency verdicts:")
        for i, verdict in enumerate(verdict_history, start=1):
            lines.append(f"{i}. {verdict}")

    source_verification = state.get("source_verification") or []
    if source_verification:
        lines.append("\n---\nSource verification:")
        for source in source_verification:
            lines.append(f"- {source}")

    return "\n".join(lines)
