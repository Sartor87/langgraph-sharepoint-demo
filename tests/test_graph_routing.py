from app.graph import route_after_evaluation


def _state(verdict: str, iteration: int, max_iterations: int = 3) -> dict:
    return {
        "sufficiency_verdict": verdict,
        "iteration": iteration,
        "max_iterations": max_iterations,
    }


def test_routes_to_agent3_when_sufficient():
    assert route_after_evaluation(_state("sufficient", iteration=1)) == "agent3"


def test_routes_to_agent1_when_insufficient_and_budget_remains():
    assert route_after_evaluation(_state("insufficient", iteration=1)) == ["agent1", "agent4"]


def test_routes_to_agent3_when_budget_exhausted_even_if_insufficient():
    assert route_after_evaluation(_state("insufficient", iteration=3)) == "agent3"


def test_route_after_evaluation_loops_to_both_agent1_and_agent4():
    state = {"sufficiency_verdict": "insufficient", "iteration": 1, "max_iterations": 3}
    result = route_after_evaluation(state)
    assert result == ["agent1", "agent4"]


def test_route_after_evaluation_escalates_to_agent3_when_sufficient():
    state = {"sufficiency_verdict": "sufficient", "iteration": 1, "max_iterations": 3}
    assert route_after_evaluation(state) == "agent3"


def test_route_after_evaluation_escalates_to_agent3_when_budget_exhausted():
    state = {"sufficiency_verdict": "insufficient", "iteration": 3, "max_iterations": 3}
    assert route_after_evaluation(state) == "agent3"
