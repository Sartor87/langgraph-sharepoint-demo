from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import _build_local_fallback_app


def test_health_endpoint():
    stub_graph = AsyncMock()
    app = _build_local_fallback_app(stub_graph)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invoke_endpoint_calls_graph_and_returns_report():
    stub_graph = AsyncMock()
    stub_graph.ainvoke.return_value = {
        "final_report": "Report text",
        "source_verification": ["doc1.pdf"],
        "verdict_history": ["sufficient"],
        "partial_evidence": False,
    }
    app = _build_local_fallback_app(stub_graph)
    client = TestClient(app)

    response = client.post("/invoke", json={"task": "Audit case #123", "thread_id": "t1"})

    assert response.status_code == 200
    assert response.json() == {
        "final_report": "Report text",
        "source_verification": ["doc1.pdf"],
        "verdict_history": ["sufficient"],
        "partial_evidence": False,
    }
    stub_graph.ainvoke.assert_awaited_once()
    call_args = stub_graph.ainvoke.call_args
    assert call_args.kwargs["config"] == {"configurable": {"thread_id": "t1"}}
