# Azure AI Foundry Hosted Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `app/main.py`'s Foundry hosting adapter real (it currently imports a nonexistent module), add a second parallel deploy target (Azure AI Foundry Hosted Agent via `azd`) alongside the existing ACI+Terraform path, and give the ACI path a durable Postgres checkpointer.

**Architecture:** The same container image serves both deploy targets. `FOUNDRY_PROJECT_ENDPOINT` being set (Foundry-injected) vs. unset (ACI) is the only branch point, checked in exactly two places: `app/graph.py`'s `_build_llm()` (which LLM client) and `app/checkpointer.py`'s `build_checkpointer()` (which checkpointer — `AsyncPostgresSaver` for ACI, `MemorySaver` for Foundry, since Foundry's runtime can't reach the private-VNet Postgres). The Responses protocol adapter (`app/responses_adapter.py`) runs identically regardless of target.

**Tech Stack:** `langchain_azure_ai.agents.hosting` (`ResponsesHostServer`), `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`), `azure-ai-projects`/`azure-identity` (Foundry auth), `azd` CLI (Foundry deploy tooling), pytest.

## Global Constraints

- Same container image must work for both ACI and Foundry — branch only on `FOUNDRY_PROJECT_ENDPOINT` presence, in `_build_llm()` and `build_checkpointer()`.
- Foundry path uses `MemorySaver` (not durable) — Postgres is private-VNet-only (`public_network_access_enabled = false`) and unreachable from Foundry's managed runtime. Do not reopen Postgres to the public internet to work around this.
- ACI path uses `AsyncPostgresSaver` against the existing Terraform-provisioned Postgres (`DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` env vars, `sslmode=require`).
- No real token-level streaming — `stream=true` gets one full delta + a completed event.
- Human-in-the-loop (`interrupt()`) is explicitly out of scope — track as a README TODO, don't build it.
- `azd provision`/`azd deploy` against a real Foundry project are manual, user-run steps — never auto-executed by any task in this plan.
- Do not fabricate the `agent.yaml`/`azd` scaffold schema — it must come from running the real `azd` scaffold tooling; if `azd` isn't available in the implementer's environment, report BLOCKED rather than inventing the file.
 
---

### Task 1: Add Foundry/Postgres dependencies

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` and `psycopg`/`psycopg_pool` become importable when the `azure` extra is installed — consumed by Task 2.

- [ ] **Step 1: Add the two new dependencies to the `azure` extra**

In `pyproject.toml`, change:

```toml
[project.optional-dependencies]
azure = [
    "langchain-azure-ai[hosting]>=1.2.4",
    "azure-identity>=1.17",
]
```

to:

```toml
[project.optional-dependencies]
azure = [
    "langchain-azure-ai[hosting]>=1.2.4",
    "azure-identity>=1.17",
    "langgraph-checkpoint-postgres>=2.0.0",
    "psycopg[binary,pool]>=3.2",
]
```

- [ ] **Step 2: Install and verify imports resolve**

Run: `pip install -e ".[azure,dev]"`
Then: `python -c "from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; from psycopg_pool import AsyncConnectionPool; print('ok')"`
Expected: prints `ok` with no `ModuleNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add Foundry/Postgres checkpoint dependencies"
```

---

### Task 2: `app/checkpointer.py` — durable checkpointer for ACI, MemorySaver for Foundry

**Files:**
- Create: `app/checkpointer.py`
- Test: `tests/test_checkpointer.py`

**Interfaces:**
- Consumes: env vars `FOUNDRY_PROJECT_ENDPOINT` (presence check), `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` (ACI path only).
- Produces: `build_checkpointer()` — an **async context manager** (decorated with `@asynccontextmanager`) yielding a LangGraph-compatible checkpointer object (`MemorySaver` or `AsyncPostgresSaver`). Consumed by Task 5/6's `app/main.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_checkpointer.py`:

```python
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_build_checkpointer_returns_memory_saver_for_foundry(monkeypatch):
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )

    from app.checkpointer import build_checkpointer

    async with build_checkpointer() as checkpointer:
        assert isinstance(checkpointer, MemorySaver)


@pytest.mark.asyncio
async def test_build_checkpointer_uses_postgres_without_foundry_endpoint(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("DB_HOST", "psql-audit-agent-dev.postgres.database.azure.com")
    monkeypatch.setenv("DB_NAME", "langgraph_checkpoints")
    monkeypatch.setenv("DB_USER", "auditagent")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")

    mock_checkpointer = AsyncMock()
    mock_saver_module = MagicMock()

    class _FakeCtx:
        async def __aenter__(self):
            return mock_checkpointer

        async def __aexit__(self, *exc):
            return False

    mock_saver_module.AsyncPostgresSaver.from_conn_string.return_value = _FakeCtx()

    with patch.dict(sys.modules, {"langgraph.checkpoint.postgres.aio": mock_saver_module}):
        from app.checkpointer import build_checkpointer

        async with build_checkpointer() as checkpointer:
            assert checkpointer is mock_checkpointer

    mock_checkpointer.setup.assert_awaited_once()
    conn_string_arg = mock_saver_module.AsyncPostgresSaver.from_conn_string.call_args[0][0]
    assert "auditagent:hunter2@psql-audit-agent-dev.postgres.database.azure.com" in conn_string_arg
    assert "sslmode=require" in conn_string_arg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_checkpointer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.checkpointer'`

- [ ] **Step 3: Write the implementation**

`app/checkpointer.py`:

```python
"""Builds the checkpointer for whichever deploy target is running.

ACI (FOUNDRY_PROJECT_ENDPOINT unset): AsyncPostgresSaver against the private-
VNet Postgres Terraform provisions — durable, survives container restarts.

Foundry Hosted Agent (FOUNDRY_PROJECT_ENDPOINT set): MemorySaver. Foundry's
managed runtime cannot reach the private-VNet-only Postgres, so state does
not survive a restart on this path yet.
TODO: wire a Cosmos DB checkpointer for the Foundry path (tracked in
README.md's Open items).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import MemorySaver


def _foundry_mode() -> bool:
    return bool(os.environ.get("FOUNDRY_PROJECT_ENDPOINT"))


def _build_postgres_conn_string() -> str:
    host = os.environ["DB_HOST"]
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]
    return f"postgresql://{user}:{password}@{host}:5432/{name}?sslmode=require"


@asynccontextmanager
async def build_checkpointer():
    if _foundry_mode():
        yield MemorySaver()
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(_build_postgres_conn_string()) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_checkpointer.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add app/checkpointer.py tests/test_checkpointer.py
git commit -m "feat: add build_checkpointer (AsyncPostgresSaver for ACI, MemorySaver for Foundry)"
```

---

### Task 3: `app/graph.py` — branch `_build_llm()` on Foundry vs ACI

**Files:**
- Modify: `app/graph.py:26-32` (the `_build_llm` function)
- Test: `tests/test_llm_builder.py`

**Interfaces:**
- Consumes: env vars `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_NAME` (Foundry path); `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` (ACI path, unchanged from current behavior).
- Produces: `_build_llm() -> BaseChatModel` — used by `build_graph()` in the same file (existing call site, unchanged).

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_builder.py`:

```python
import sys
from unittest.mock import MagicMock, patch


def test_build_llm_uses_azure_openai_without_foundry_endpoint(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")

    from app.graph import _build_llm
    from langchain_openai import AzureChatOpenAI

    llm = _build_llm()

    assert isinstance(llm, AzureChatOpenAI)


def test_build_llm_uses_foundry_client_with_foundry_endpoint(monkeypatch):
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("FOUNDRY_MODEL_NAME", "gpt-4.1")

    mock_projects_module = MagicMock()
    mock_identity_module = MagicMock()
    mock_credential = MagicMock()
    mock_identity_module.DefaultAzureCredential.return_value = mock_credential
    mock_identity_module.get_bearer_token_provider.return_value = lambda: "fake-token"

    mock_project_client = MagicMock()
    mock_openai_client = MagicMock()
    mock_openai_client.base_url = "https://example.services.ai.azure.com/api/projects/demo/openai/"
    mock_project_client.get_openai_client.return_value = mock_openai_client
    mock_projects_module.AIProjectClient.return_value = mock_project_client

    with patch.dict(
        sys.modules,
        {"azure.ai.projects": mock_projects_module, "azure.identity": mock_identity_module},
    ):
        from app.graph import _build_llm
        from langchain_openai import ChatOpenAI

        llm = _build_llm()

    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4.1"
    mock_projects_module.AIProjectClient.assert_called_once_with(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        credential=mock_credential,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_builder.py -v`
Expected: first test passes already (existing behavior); second FAILs — `_build_llm` doesn't yet check `FOUNDRY_PROJECT_ENDPOINT`, so `AIProjectClient` mock is never called and `llm` is an `AzureChatOpenAI` missing `AZURE_OPENAI_ENDPOINT` (raises `KeyError`).

- [ ] **Step 3: Write the implementation**

In `app/graph.py`, replace:

```python
def _build_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        temperature=0,
    )
```

with:

```python
def _build_llm() -> BaseChatModel:
    foundry_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if foundry_endpoint:
        return _build_foundry_llm(foundry_endpoint)

    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        temperature=0,
    )


def _build_foundry_llm(foundry_endpoint: str) -> ChatOpenAI:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=foundry_endpoint.rstrip("/"), credential=credential)
    openai_client = project.get_openai_client()
    token_provider = get_bearer_token_provider(credential, "https://ai.azure.com/.default")

    return ChatOpenAI(
        model=os.environ.get("FOUNDRY_MODEL_NAME", "gpt-4.1"),
        base_url=str(openai_client.base_url),
        api_key=token_provider,
    )
```

Add to the imports at the top of `app/graph.py`:

```python
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI
```

(replacing the existing `from langchain_openai import AzureChatOpenAI` line).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_builder.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: all tests pass (existing `test_graph_routing.py` and `test_state_schema.py` unaffected — `_build_llm`'s call site and signature-shape are unchanged, only its internals branch).

- [ ] **Step 6: Commit**

```bash
git add app/graph.py tests/test_llm_builder.py
git commit -m "feat: branch _build_llm on FOUNDRY_PROJECT_ENDPOINT"
```

---

### Task 4: `app/responses_adapter.py` — pure input/output mapping helpers

**Files:**
- Create: `app/responses_adapter.py`
- Test: `tests/test_responses_adapter.py`

**Interfaces:**
- Consumes: `app.schemas.state.AuditState` (existing TypedDict — no changes).
- Produces: `extract_task_text(input_data) -> str` and `build_output_text(state: AuditState) -> str`, both pure functions with no I/O. Consumed by Task 6's `AuditResponsesHostServer`.

- [ ] **Step 1: Write the failing tests**

`tests/test_responses_adapter.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_responses_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.responses_adapter'`

- [ ] **Step 3: Write the implementation**

`app/responses_adapter.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_responses_adapter.py -v`
Expected: PASS (7/7)

- [ ] **Step 5: Commit**

```bash
git add app/responses_adapter.py tests/test_responses_adapter.py
git commit -m "feat: add extract_task_text/build_output_text for the Responses adapter"
```

---

### Task 5: `app/main.py` — wiring skeleton + local fallback (testable)

**Files:**
- Modify: `app/main.py` (full rewrite)
- Test: `tests/test_main_fallback.py`

**Interfaces:**
- Consumes: `app.checkpointer.build_checkpointer` (Task 2), `app.graph.build_graph`/`initial_state` (existing, Task 3's changes don't affect this call site's signature).
- Produces: `_build_local_fallback_app(graph) -> FastAPI` (a plain function returning a FastAPI app object, not module-level — this is what makes it unit-testable without starting a real server). Consumed by Task 6 (which adds the Foundry/Responses branch alongside this fallback).

This task intentionally does NOT yet wire in the real `ResponsesHostServer` — it establishes the local-fallback path (which is fully testable today) and a `_serve()` skeleton with a clearly marked gap for Task 6 to fill in, so this task's deliverable (the fallback path working, tested) can be reviewed independently of Task 6's higher-risk spike.

- [ ] **Step 1: Write the failing tests**

`tests/test_main_fallback.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_fallback.py -v`
Expected: FAIL — `app.main` doesn't yet define `_build_local_fallback_app` (current `app/main.py` builds a module-level `app` variable instead).

- [ ] **Step 3: Write the implementation**

Replace the full contents of `app/main.py` with:

```python
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

from app.checkpointer import build_checkpointer
from app.graph import build_graph, initial_state


def _build_local_fallback_app(graph):
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="langgraph-sharepoint-demo (local fallback)")

    class InvokeRequest(BaseModel):
        task: str
        thread_id: str = "local-dev"

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main_fallback.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main_fallback.py
git commit -m "feat: rewrite main.py wiring — testable local fallback, Foundry path stubbed"
```

---

### Task 6: Wire the real `ResponsesHostServer` (spike — requires package inspection)

**Files:**
- Modify: `app/responses_adapter.py` (add the `AuditResponsesHostServer` class)
- Modify: `app/main.py:_serve()` (replace the `NotImplementedError` stub from Task 5)
- Test: extend `tests/test_responses_adapter.py` (exact tests depend on what Step 1 finds — see Step 4)

**Interfaces:**
- Consumes: `extract_task_text`/`build_output_text` (Task 4), `build_checkpointer` (Task 2), the `_serve()`/`_build_local_fallback_app` skeleton (Task 5).
- Produces: a working `/responses` endpoint on both deploy targets.

**Why this task looks different from the others:** the documentation available for this integration shows `ResponsesHostServer(graph).run(port=port)` as the top-level entrypoint and names `build_input`/`handle_create` as the override points for custom (non-`messages`) graph state, but doesn't give their exact signatures or confirm whether `.run()` can be called from inside an already-running event loop (which matters here, since Task 2's `build_checkpointer()` is an `async with` block and `.run()` needs to execute inside it). Rather than guess and risk shipping code against a fictional API, this task starts by inspecting the real installed package.

- [ ] **Step 1: Inspect the installed package**

Run:

```bash
python -c "
import inspect
from langchain_azure_ai.agents.hosting import ResponsesHostServer
print('--- run ---')
print(inspect.signature(ResponsesHostServer.run))
print(inspect.getsource(ResponsesHostServer.run))
print('--- handle_create ---')
print(inspect.signature(ResponsesHostServer.handle_create))
print(inspect.getsource(ResponsesHostServer.handle_create))
print('--- build_input ---')
print(inspect.signature(ResponsesHostServer.build_input))
"
```

Record the output in your task report verbatim — the next steps depend on it. Specifically answer:
1. Is there an async-callable entrypoint (e.g. `arun`/`serve`) distinct from the synchronous `run`? Does `run` itself just wrap `asyncio.run(...)` around an async method?
2. What does `handle_create` receive (a raw ASGI request? A parsed Pydantic model?) and what must it return (a `Response` object? Does it write to a stream/emitter passed as an argument?) — read the base class's own implementation of `handle_create` for the pattern to follow.
3. Does `ResponsesHostServer` expose its underlying ASGI app (e.g. a `.app` attribute) that would allow adding a Starlette/FastAPI `lifespan` startup hook — useful if `run()` truly can't be called from inside `build_checkpointer()`'s `async with` block, since a startup hook running inside `run()`'s own event loop would be the safe place to open the checkpointer's connection pool instead.

If `langchain_azure_ai.agents.hosting` isn't importable at all (package not installed successfully, or a version mismatch with what Task 1 pinned), report BLOCKED with the exact `ImportError` rather than guessing.

- [ ] **Step 2: Decide the integration shape based on Step 1's findings**

- **If `run`/an async equivalent CAN be awaited from inside an already-running loop:** keep Task 5's structure — build the `AuditResponsesHostServer(graph)` instance inside `_serve()`'s `async with build_checkpointer()` block, call the async entrypoint there.
- **If it CANNOT** (calling it raises `RuntimeError: asyncio.run() cannot be called from a running event loop` or similar): restructure so the host server's blocking `run()` is called from plain sync code in `__main__` (not from inside `asyncio.run(_serve())`), and instead use the ASGI app's `lifespan`/startup hook (if Step 1 found one) to open the checkpointer's connection pool in the same loop `run()` itself uses. Document whichever shape you used in your task report, since it changes what Task 5's skeleton looks like.

- [ ] **Step 3: Implement `AuditResponsesHostServer`**

Add to `app/responses_adapter.py`, using the real signature found in Step 1 (this is necessarily written against what you found, not copy-pasted verbatim — the shape below is the behavior contract, not the exact code):

- Override the hook(s) found in Step 1 so that, for each incoming request:
  1. Parse `input`, `previous_response_id` (or `conversation`), and `stream` from the request per the real signature.
  2. `task_text = extract_task_text(input)`.
  3. `thread_id = previous_response_id or <generate a new id, e.g. str(uuid4())>`.
  4. `state = initial_state(task_text)`; `result = await self.graph.ainvoke(state, config={"configurable": {"thread_id": thread_id}})`.
  5. `output_text = build_output_text(result)`.
  6. If `stream` is falsy: return/emit a single completed response containing `output_text` (per the real API's response-construction pattern).
  7. If `stream` is truthy: emit one delta event containing the full `output_text`, then a completed event — do not build real token-level streaming.

- [ ] **Step 4: Write tests matching what Step 1 found**

The exact test structure depends on Step 1's answer to "what does the hook receive/return." If it's a Starlette-style request/response (most likely, given `InvocationsHostServer`'s documented `parse_request(self, request: Request)` signature), write an integration test using the package's own test utilities if it ships any, or construct a minimal fake request object matching the real signature and call the overridden method directly, asserting the returned/emitted response contains `output_text`'s content. Use a stub graph (`AsyncMock` with `.ainvoke.return_value` set to a canned `AuditState` dict, same pattern as `tests/test_main_fallback.py`) — do not require a real LLM or real Foundry credentials for this test.

- [ ] **Step 5: Replace `app/main.py`'s stub**

Replace the `NotImplementedError` block from Task 5 with the real instantiation-and-run call, per whichever shape Step 2 decided.

- [ ] **Step 6: Run tests**

Run: `pytest tests/ -v`
Expected: all tests pass, including the new ones from Step 4.

- [ ] **Step 7: Manual smoke test**

With a real (or dev) Foundry project:

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL_NAME="gpt-4.1"
python -m app.main
```

In another terminal:

```bash
curl -sS -H "Content-Type: application/json" \
  -X POST http://localhost:8088/responses \
  -d '{"input":"Audit retention policy docs for case #4471","stream":false}'
```

Expected: a Responses-shaped JSON response whose output text contains a report (or, if the SharePoint sidecar isn't running, whatever error `app/tools/sharepoint_tool.py`'s `NotImplementedError` propagates as — that's expected and not a bug in this task, since the sidecar is still unscaffolded per README's existing TODO list).

- [ ] **Step 8: Commit**

```bash
git add app/responses_adapter.py app/main.py tests/test_responses_adapter.py
git commit -m "feat: wire real ResponsesHostServer for AuditState"
```

---

### Task 7: `docker/Dockerfile` — run `main.py` as a script

**Files:**
- Modify: `docker/Dockerfile`

**Interfaces:** None — this only changes the container's startup command.

- [ ] **Step 1: Update the CMD**

In `docker/Dockerfile`, replace:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

with:

```dockerfile
CMD ["python", "-m", "app.main"]
```

- [ ] **Step 2: Build and smoke-test locally**

Run: `docker build -t audit-agent-test -f docker/Dockerfile .`
Then: `docker run --rm -e AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com/ -e AZURE_OPENAI_API_KEY=test -e DB_HOST=localhost -e DB_NAME=test -e DB_USER=test -e DB_PASSWORD=test -p 8000:8000 audit-agent-test`
Expected: the container starts and attempts to connect (it's fine if it fails to actually reach a real Postgres/OpenAI — confirm it fails with a *connection* error, not an `ImportError`/`ModuleNotFoundError`/`SyntaxError`, which would indicate the CMD change or Task 6's code has a packaging problem).

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile
git commit -m "fix: run app/main.py as a script instead of importing an ASGI app"
```

---

### Task 8: Terraform — add `DB_USER` to the ACI container's env vars

**Files:**
- Modify: `terraform/environments/dev/main.tf:118-126` (the `module.audit_agent`'s `environment_variables` block)

**Interfaces:** None — Terraform-only change, no code interface.

- [ ] **Step 1: Add `DB_USER`**

In `terraform/environments/dev/main.tf`, in the `module "audit_agent"` block's `environment_variables`, add a line so the block reads:

```hcl
  environment_variables = {
    AZURE_OPENAI_ENDPOINT                 = var.azure_openai_endpoint
    AZURE_OPENAI_DEPLOYMENT               = var.azure_openai_deployment
    SHAREPOINT_SERVICE_URL                = var.sharepoint_service_url
    SHAREPOINT_SITE_URL                   = var.sharepoint_site_url
    DB_HOST                               = module.postgres.fqdn
    DB_NAME                               = module.postgres.database_name
    DB_USER                               = "auditagent"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
  }
```

(only the `DB_USER = "auditagent"` line is new — it must match the hardcoded `administrator_login` in `terraform/modules/postgres/main.tf`.)

- [ ] **Step 2: Validate**

Run: `cd terraform/environments/dev && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Format**

Run: `cd terraform && terraform fmt -recursive` then `terraform fmt -check -recursive`
Expected: second command exits 0 with no output.

- [ ] **Step 4: Commit**

```bash
git add terraform/environments/dev/main.tf
git commit -m "feat(terraform): pass DB_USER to the audit-agent container"
```

---

### Task 9: `foundry/` — azd scaffold for Foundry Hosted Agent deploy

**Files:**
- Create: `foundry/agent.yaml` (content determined by the real `azd` scaffold — see Step 1)
- Create: `foundry/README.md`

**Interfaces:** None — deployment configuration and docs only.

- [ ] **Step 1: Run the real azd scaffold tooling**

Run: `azd version` to confirm the CLI is available.

If it is NOT available: report BLOCKED — do not hand-author `agent.yaml`'s schema from the partial documentation available for this task; that schema must come from the real tool.

If it IS available, run (in a scratch directory, not this repo, so you can inspect the output before copying anything in):

```bash
mkdir /tmp/foundry-scaffold-scratch && cd /tmp/foundry-scaffold-scratch
azd ext install azure.ai.agents
azd auth login
azd ai agent init
```

Follow the prompts (select "Responses" protocol, Python, point at an existing Foundry project if you have one available, or create a new one if prompted — this is local scaffolding only, no resources are provisioned by `init` itself).

- [ ] **Step 2: Adapt the generated files into `foundry/`**

Copy the generated `agent.yaml` (and any other files `azd ai agent init` produced beyond a sample `main.py`/`Dockerfile`, which this repo already has its own versions of at `app/main.py`/`docker/Dockerfile`) into `foundry/agent.yaml` in this repo. Edit it to point at:
- This repo's `docker/Dockerfile` (not the scaffold's sample Dockerfile).
- `app/main.py` as the entrypoint (already correct after Task 7's Dockerfile change).
- The env vars this app actually needs: `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_NAME` (both Foundry-injected, don't set them yourself in the manifest — confirm the generated file doesn't hardcode placeholder values for these).

Document in your task report exactly what the generated `agent.yaml`'s schema looked like (field names, structure) since this is the first time this repo has one — the review needs to confirm it wasn't fabricated.

- [ ] **Step 3: Write `foundry/README.md`**

```markdown
# Foundry Hosted Agent deployment

Second, parallel deploy target alongside the ACI + Terraform path
(`terraform/README.md`) — same container image, different runtime.

## Prerequisites

- An Azure AI Foundry project with a deployed chat model (e.g. `gpt-4.1`).
- `az login` (for `DefaultAzureCredential`).
- `azd` CLI with the AI agent extension: `azd ext install azure.ai.agents`.
- Docker running locally (azd builds the image from `docker/Dockerfile`).

## Local test

\`\`\`bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL_NAME="gpt-4.1"
python -m app.main
\`\`\`

In another terminal:

\`\`\`bash
curl -sS -H "Content-Type: application/json" \
  -X POST http://localhost:8088/responses \
  -d '{"input":"Audit retention policy docs for case #4471","stream":false}'
\`\`\`

## Deploy (manual — real, billed Azure actions)

\`\`\`bash
cd foundry
azd auth login
azd provision   # only if this is a brand-new Foundry project/model deployment
azd deploy
\`\`\`

Requires the **Foundry Project Manager** role on the target project.

## Checkpointer note

This deploy target uses `MemorySaver` (non-durable) — Foundry's managed
runtime can't reach the private-VNet-only Postgres the ACI path uses. See
`docs/superpowers/specs/2026-07-06-foundry-hosted-agent-design.md` and
README.md's Open items (Cosmos DB checkpointer, tracked as future work).
```

- [ ] **Step 4: Commit**

```bash
git add foundry/
git commit -m "feat: scaffold Foundry Hosted Agent azd deployment"
```

---

### Task 10: Documentation — README updates

**Files:**
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Fix the Local development section**

`app/main.py` is no longer uvicorn-importable (Task 5 removed the module-level `app` variable). In `README.md`'s "Local development" section, replace:

```bash
uvicorn app.main:app --reload --port 8000
```

with:

```bash
python -m app.main
```

- [ ] **Step 2: Expand Deployment path item 2**

Replace the current one-liner Foundry item in `README.md`'s "Deployment path" section with:

```markdown
2. **Azure AI Foundry Hosted Agent** (second, parallel deploy target,
   currently preview) — same container image as the ACI path above; Foundry
   injects `FOUNDRY_PROJECT_ENDPOINT`/`FOUNDRY_MODEL_NAME` at runtime, which
   `app/graph.py`'s `_build_llm()` and `app/checkpointer.py`'s
   `build_checkpointer()` both branch on. Deploy via `azd` — see
   `foundry/README.md`. This path uses `MemorySaver` (non-durable) since
   Foundry's runtime can't reach the ACI path's private-VNet Postgres.
```

- [ ] **Step 3: Add two TODO items**

In `README.md`'s "Open items / TODO" section, add:

```markdown
- [ ] Wire human-in-the-loop (`interrupt()`) once the `requires_human_review`
      graph branch exists — the Responses protocol already supports resuming
      via `function_call_output`/`mcp_approval_response`.
- [ ] Wire a Cosmos DB checkpointer for the Foundry Hosted Agent path
      (currently `MemorySaver`, non-durable — Postgres isn't reachable from
      Foundry's runtime since it's private-VNet-only).
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for the Foundry Hosted Agent deploy path"
```
