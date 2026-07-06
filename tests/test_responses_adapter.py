import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.responses_adapter import build_output_text, extract_task_text

try:
    import langchain_azure_ai.agents.hosting  # noqa: F401

    _HAS_AZURE_HOSTING = True
except Exception:  # pragma: no cover - depends on optional extra
    _HAS_AZURE_HOSTING = False

requires_hosting = pytest.mark.skipif(
    not _HAS_AZURE_HOSTING,
    reason="azure hosting extra (langchain_azure_ai) not installed",
)


def test_extract_task_text_from_plain_string():
    assert extract_task_text("Audit case #123") == "Audit case #123"


def test_extract_task_text_from_message_list():
    input_data = [
        {"role": "user", "content": "first message, ignored"},
        {"role": "assistant", "content": "a reply"},
        {"role": "user", "content": "Audit case #123"},
    ]
    assert extract_task_text(input_data) == "Audit case #123"


def test_extract_task_text_from_message_list_with_content_parts():
    input_data = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Audit case "},
                {"type": "input_text", "text": "#123"},
            ],
        }
    ]
    assert extract_task_text(input_data) == "Audit case \n#123"


def test_extract_task_text_raises_when_no_user_message():
    with pytest.raises(ValueError):
        extract_task_text([{"role": "assistant", "content": "only a reply"}])


def _final_report(**overrides):
    report = {
        "task": "Audit case #123",
        "summary": "All documents accounted for.",
        "findings": [],
        "partial_evidence": False,
        "source_count": 1,
        "excluded_source_count": 0,
    }
    report.update(overrides)
    return report


def test_build_output_text_includes_final_report():
    state = {
        "final_report": _final_report(),
        "partial_evidence": False,
        "verdict_history": [],
        "source_verification": [],
    }
    assert build_output_text(state) == "All documents accounted for."


def test_build_output_text_includes_findings_as_bullets():
    state = {
        "final_report": _final_report(
            summary="Report.", findings=["Policy is current.", "No conflicts found."]
        ),
        "partial_evidence": False,
        "verdict_history": [],
        "source_verification": [],
    }
    output = build_output_text(state)
    assert "Report." in output
    assert "- Policy is current." in output
    assert "- No conflicts found." in output


def test_build_output_text_flags_partial_evidence():
    state = {
        "final_report": _final_report(
            summary="Best-effort report.", partial_evidence=True
        ),
        "partial_evidence": True,
        "verdict_history": [],
        "source_verification": [],
    }
    output = build_output_text(state)
    assert output.startswith("NOTE: this result is partial")
    assert "Best-effort report." in output


def test_build_output_text_no_report_produced():
    state = {
        "final_report": None,
        "partial_evidence": False,
        "verdict_history": [],
        "source_verification": [],
    }
    assert build_output_text(state) == "(no report produced)"


def test_build_output_text_no_report_but_partial_evidence_from_top_level_state():
    state = {
        "final_report": None,
        "partial_evidence": True,
        "verdict_history": [],
        "source_verification": [],
    }
    output = build_output_text(state)
    assert output.startswith("NOTE: this result is partial")
    assert "(no report produced)" in output


def test_build_output_text_appends_verdict_history_and_sources():
    state = {
        "final_report": _final_report(summary="Report."),
        "partial_evidence": False,
        "verdict_history": [
            {
                "decision": "insufficient",
                "confidence": 0.4,
                "reasoning": "Missing recent policy versions.",
                "insufficiency_reasons": ["partial_coverage"],
                "refined_query": "policy v2",
                "missing_aspects": [],
                "document_assessments": [],
                "requires_human_review": False,
            },
            {
                "decision": "sufficient",
                "confidence": 0.9,
                "reasoning": "All aspects covered.",
                "insufficiency_reasons": [],
                "refined_query": None,
                "missing_aspects": [],
                "document_assessments": [],
                "requires_human_review": False,
            },
        ],
        "source_verification": [
            {
                "doc_id": "policy.pdf",
                "verified": True,
                "verification_notes": "Metadata present.",
                "excluded_from_report": False,
            }
        ],
    }
    output = build_output_text(state)
    assert "Sufficiency verdicts:" in output
    assert "1. insufficient (confidence: 0.40) — Missing recent policy versions." in output
    assert "2. sufficient (confidence: 0.90) — All aspects covered." in output
    assert "Source verification:" in output
    assert "- policy.pdf: verified — Metadata present." in output


# ---------------------------------------------------------------------------
# AuditResponsesHostServer.handle_create integration tests
#
# These construct the ResponsesHostServer subclass via `__new__` to bypass the
# real host's __init__ (which stands up an ASGI host, telemetry, and a store).
# handle_create only touches `self.graph` and inherited request/context
# helpers, so setting `_graph` on the bare instance is sufficient. The graph is
# an AsyncMock returning a canned AuditState — no real LLM or Foundry needed.
# ---------------------------------------------------------------------------


def _make_server(graph):
    from app.responses_adapter import _audit_host_server_class

    cls = _audit_host_server_class()
    server = cls.__new__(cls)
    server._graph = graph
    return server


def _drive(server, request, context):
    async def _collect():
        events = []
        async for event in server.handle_create(request, context, asyncio.Event()):
            events.append(event)
        return events

    return asyncio.run(_collect())


def _event_types(events):
    return [getattr(e, "type", None) for e in events]


@requires_hosting
def test_handle_create_runs_graph_and_emits_report():
    canned = {
        "final_report": {
            "summary": "All accounted for.",
            "findings": ["Policy is current."],
            "partial_evidence": False,
        },
        "partial_evidence": False,
        "verdict_history": [],
        "source_verification": [],
    }
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(return_value=canned)
    server = _make_server(graph)

    request = SimpleNamespace(input="Audit case #4471", previous_response_id=None)
    context = SimpleNamespace(response_id="resp_abc", conversation_id=None)

    events = _drive(server, request, context)

    # Graph driven once, on a fresh AuditState carrying the extracted task text
    # and a checkpointer thread id.
    graph.ainvoke.assert_awaited_once()
    state_arg = graph.ainvoke.await_args.args[0]
    assert state_arg["task"] == "Audit case #4471"
    thread_id = graph.ainvoke.await_args.kwargs["config"]["configurable"]["thread_id"]
    assert thread_id

    types = _event_types(events)
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"

    # The full report is delivered as a single output_text delta.
    deltas = [
        getattr(e, "delta", None)
        for e in events
        if getattr(e, "type", None) == "response.output_text.delta"
    ]
    assert deltas == [build_output_text(canned)]


@requires_hosting
def test_handle_create_threads_previous_response_id():
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "final_report": None,
            "partial_evidence": False,
            "verdict_history": [],
            "source_verification": [],
        }
    )
    server = _make_server(graph)

    request = SimpleNamespace(input="follow-up", previous_response_id="resp_prev")
    context = SimpleNamespace(response_id="resp_new", conversation_id=None)

    _drive(server, request, context)

    thread_id = graph.ainvoke.await_args.kwargs["config"]["configurable"]["thread_id"]
    assert "resp_prev" in thread_id


@requires_hosting
def test_handle_create_emits_failed_on_graph_error():
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(side_effect=RuntimeError("sharepoint sidecar down"))
    server = _make_server(graph)

    request = SimpleNamespace(input="Audit case #4471", previous_response_id=None)
    context = SimpleNamespace(response_id="resp_err", conversation_id=None)

    events = _drive(server, request, context)

    types = _event_types(events)
    assert "response.failed" in types
    assert "response.completed" not in types
