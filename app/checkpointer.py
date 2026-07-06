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
