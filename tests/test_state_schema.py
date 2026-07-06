import pytest
from pydantic import ValidationError

from app.schemas.state import InsufficiencyReason, SufficiencyVerdict


def test_sufficient_verdict_valid():
    verdict = SufficiencyVerdict(
        decision="sufficient",
        confidence=0.9,
        reasoning="All required aspects are covered.",
    )
    assert verdict.requires_human_review is False


def test_insufficient_requires_refined_query():
    with pytest.raises(ValidationError):
        SufficiencyVerdict(
            decision="insufficient",
            confidence=0.4,
            reasoning="Missing coverage.",
            refined_query=None,
        )


def test_sufficient_cannot_have_insufficiency_reasons():
    with pytest.raises(ValidationError):
        SufficiencyVerdict(
            decision="sufficient",
            confidence=0.9,
            reasoning="ok",
            insufficiency_reasons=[InsufficiencyReason.PARTIAL_COVERAGE],
        )


def test_conflicting_sources_forces_human_review():
    verdict = SufficiencyVerdict(
        decision="insufficient",
        confidence=0.5,
        reasoning="Sources disagree on effective date.",
        refined_query="effective date policy XYZ",
        insufficiency_reasons=[InsufficiencyReason.CONFLICTING_SOURCES],
        requires_human_review=False,  # should be overridden to True
    )
    assert verdict.requires_human_review is True
