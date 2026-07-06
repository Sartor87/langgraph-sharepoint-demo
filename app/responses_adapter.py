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

import logging
from typing import cast

from app.schemas.state import AuditState

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Foundry Responses hosting glue
#
# The exact API below was pinned by inspecting the installed
# langchain_azure_ai package (see Task 6). Key facts the shape here depends on:
#
#   * ResponsesHostServer.__init__ runs `_validate_graph_schema(graph)` and
#     RAISES ValueError unless the graph's state schema declares a `messages`
#     field. AuditState declares none, so the subclass relaxes that guard.
#   * The default request->graph->response pipeline (`build_input` /
#     `state_to_events`) only understands `{"messages": [...]}` state and
#     AIMessage/ToolMessage output — neither of which AuditState has — so this
#     subclass overrides `handle_create` wholesale rather than just
#     `build_input`, and renders the graph result via `build_output_text`.
#   * `run_async()` is a true async entrypoint (`await hypercorn.serve(...)`),
#     safe to await from inside an already-running event loop; the sync
#     `run()` wraps `asyncio.run(...)` and must NOT be used from within one.
#
# ResponsesHostServer / ResponseEventStream are imported lazily so that the
# pure functions above (and the local FastAPI fallback in app/main.py) remain
# importable without the optional `azure` hosting extra installed.
# ---------------------------------------------------------------------------


def _audit_host_server_class():
    """Build the ResponsesHostServer subclass, importing the optional deps lazily."""
    from azure.ai.agentserver.responses.streaming import ResponseEventStream
    from langchain_azure_ai.agents.hosting import ResponsesHostServer

    from app.graph import initial_state

    class AuditResponsesHostServer(ResponsesHostServer):
        """Hosts the custom-state AuditState graph on the Responses protocol."""

        @staticmethod
        def _validate_graph_schema(graph) -> None:
            # AuditState is deliberately not a `messages`-shaped schema; this
            # subclass owns the full input/output translation, so the base
            # class's messages-only guard does not apply.
            return None

        async def handle_create(self, request, context, cancellation_signal):
            """Drive the audit graph and emit Responses API events.

            Replaces the base implementation (which assumes a messages-shaped
            graph). For each request: extract the task text, run the graph on
            a fresh AuditState under a checkpointer thread derived from
            `previous_response_id`/`conversation`, then emit the rendered
            report as a single message output item. `emit_completed()` closes
            a non-streaming turn; for a streaming request the same events are
            framed as SSE by the host, with the whole report delivered as one
            `output_text.delta` (no token-level streaming).
            """
            stream = ResponseEventStream(
                response_id=context.response_id, request=request
            )
            yield stream.emit_created()
            yield stream.emit_in_progress()

            try:
                config = await self.build_runnable_config(request, context)

                try:
                    task_text = extract_task_text(request.input)
                except (ValueError, AttributeError, TypeError):
                    # Fall back to the host's own resolver for input shapes
                    # extract_task_text can't parse (e.g. resolved item refs).
                    task_text = await context.get_input_text()

                result = cast(
                    AuditState,
                    await self.graph.ainvoke(initial_state(task_text), config=config),
                )
                output_text = build_output_text(result)

                async for event in stream.aoutput_item_message(output_text):
                    yield event

                yield stream.emit_completed()
            except Exception as exc:  # noqa: BLE001
                logger.exception("AuditState response handler failed")
                yield stream.emit_failed(code="internal_error", message=str(exc))

    return AuditResponsesHostServer


def build_audit_host_server(graph):
    """Instantiate the AuditState Responses host for `graph`.

    Requires the optional `azure` hosting extra (langchain_azure_ai +
    azure-ai-agentserver). Call `.run_async(host=..., port=...)` on the result
    from inside an existing event loop to start serving `POST /responses`.
    """
    return _audit_host_server_class()(graph)
