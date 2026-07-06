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
