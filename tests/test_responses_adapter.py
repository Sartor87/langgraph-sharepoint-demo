import pytest

from app.responses_adapter import build_output_text, extract_task_text


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
