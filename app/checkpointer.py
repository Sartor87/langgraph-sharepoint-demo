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

import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


def _foundry_mode() -> bool:
    return bool(os.environ.get("FOUNDRY_PROJECT_ENDPOINT"))


def _build_postgres_conn_string() -> str:
    host = os.environ["DB_HOST"]
    name = os.environ["DB_NAME"]
    user = quote_plus(os.environ["DB_USER"])
    password = quote_plus(os.environ["DB_PASSWORD"])
    return f"postgresql://{user}:{password}@{host}:5432/{name}?sslmode=require"


@asynccontextmanager
async def build_checkpointer():
    if _foundry_mode():
        yield MemorySaver()
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn_string = _build_postgres_conn_string()
    except (ImportError, KeyError) as exc:
        # Expected in bare local dev (no `azure` extra installed, no DB_*
        # env vars set) — that's the scenario _run_local_fallback in
        # app/main.py exists for. In a real ACI deployment the `azure`
        # extra is installed and DB_* are set by Terraform, so this branch
        # should never be hit there.
        logger.warning(
            "Postgres checkpointer unavailable (%s) — falling back to "
            "MemorySaver. This is expected in local dev without the azure "
            "extra / DB_* env vars; it should never happen in a real ACI "
            "deployment.",
            exc,
        )
        yield MemorySaver()
        return

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
