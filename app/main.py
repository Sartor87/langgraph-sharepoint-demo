"""Entrypoint.

Runs the compiled LangGraph audit graph behind either:
  - the Foundry Responses protocol adapter (when the `azure` extra with
    Foundry hosting support is installed) — used on both the ACI deploy
    target and the Foundry Hosted Agent target, since FOUNDRY_PROJECT_ENDPOINT
    (not package availability) is what actually distinguishes them; or
  - a minimal local FastAPI fallback (`/invoke`, `/health`) for local dev
    without the azure extra installed.

Run directly: `python -m app.main` (not `uvicorn app.main:app` — the Foundry
hosting server manages its own run loop, so there is no ASGI `app` variable
to import).
"""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel

from app.checkpointer import build_checkpointer
from app.graph import build_graph, initial_state


class InvokeRequest(BaseModel):
    """Request body for the local-fallback `/invoke` endpoint.

    Defined at module scope (not nested inside `_build_local_fallback_app`)
    because this module uses `from __future__ import annotations` (PEP 563):
    with deferred evaluation, FastAPI resolves the `req: InvokeRequest`
    annotation via `typing.get_type_hints` against the *module's* globals,
    which cannot see a class defined inside the enclosing function. A
    function-local `InvokeRequest` would silently fail that lookup and
    FastAPI would fall back to treating `req` as a required query parameter
    instead of a JSON body.
    """

    task: str
    thread_id: str = "local-dev"


def _build_local_fallback_app(graph):
    from fastapi import FastAPI

    app = FastAPI(title="langgraph-sharepoint-demo (local fallback)")

    @app.post("/invoke")
    async def invoke(req: InvokeRequest):
        config = {"configurable": {"thread_id": req.thread_id}}
        result = await graph.ainvoke(initial_state(req.task), config=config)
        return {
            "final_report": result["final_report"],
            "source_verification": result["source_verification"],
            "verdict_history": result["verdict_history"],
            "partial_evidence": result["partial_evidence"],
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def _run_local_fallback(graph, port: int) -> None:
    import uvicorn

    uvicorn.run(_build_local_fallback_app(graph), host="0.0.0.0", port=port)


async def _serve() -> None:
    default_port = "8088" if os.environ.get("FOUNDRY_PROJECT_ENDPOINT") else "8000"
    port = int(os.environ.get("PORT", default_port))

    async with build_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        try:
            import langchain_azure_ai.agents.hosting  # noqa: F401
        except ImportError:
            _run_local_fallback(graph, port)
            return

        # Task 6 fills this in: instantiate and run the real
        # AuditResponsesHostServer(graph) here, once the installed package's
        # exact async-compatible entrypoint (or restructuring needed to avoid
        # nested event loops) has been confirmed.
        raise NotImplementedError(
            "Foundry Responses hosting is not wired up yet — see Task 6 of "
            "docs/superpowers/plans/2026-07-06-foundry-hosted-agent.md"
        )


if __name__ == "__main__":
    asyncio.run(_serve())
