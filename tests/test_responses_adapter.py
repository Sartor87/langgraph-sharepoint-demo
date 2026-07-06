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


def test_build_output_text_includes_final_report():
    state = {
        "final_report": "All documents accounted for.",
        "partial_evidence": False,
        "verdict_history": [],
        "source_verification": [],
    }
    assert build_output_text(state) == "All documents accounted for."


def test_build_output_text_flags_partial_evidence():
    state = {
        "final_report": "Best-effort report.",
        "partial_evidence": True,
        "verdict_history": [],
        "source_verification": [],
    }
    output = build_output_text(state)
    assert output.startswith("NOTE: this result is partial")
    assert "Best-effort report." in output


def test_build_output_text_appends_verdict_history_and_sources():
    state = {
        "final_report": "Report.",
        "partial_evidence": False,
        "verdict_history": ["insufficient", "sufficient"],
        "source_verification": ["policy.pdf"],
    }
    output = build_output_text(state)
    assert "Sufficiency verdicts:" in output
    assert "1. insufficient" in output
    assert "2. sufficient" in output
    assert "Source verification:" in output
    assert "- policy.pdf" in output
