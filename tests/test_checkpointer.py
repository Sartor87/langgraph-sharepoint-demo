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
    # Contains characters (`@` and `:`) that are not valid unescaped in the
    # userinfo portion of a URI, to exercise the quote_plus encoding.
    monkeypatch.setenv("DB_PASSWORD", "hunter2@weird:pass")

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
    assert "auditagent:hunter2%40weird%3Apass@psql-audit-agent-dev.postgres.database.azure.com" in conn_string_arg
    assert "sslmode=require" in conn_string_arg
    # Unencoded raw password/separator must not leak into the DSN.
    assert "hunter2@weird:pass" not in conn_string_arg


@pytest.mark.asyncio
async def test_build_checkpointer_falls_back_to_memory_saver_in_bare_local_dev(monkeypatch):
    """Bare local dev: no FOUNDRY_PROJECT_ENDPOINT, no DB_* env vars, and no
    guarantee the `azure`/postgres extra is installed. build_checkpointer()
    must degrade to MemorySaver instead of raising ModuleNotFoundError/KeyError,
    since this is exactly the scenario _run_local_fallback in app/main.py
    exists to handle."""
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    from app.checkpointer import build_checkpointer

    async with build_checkpointer() as checkpointer:
        assert isinstance(checkpointer, MemorySaver)
