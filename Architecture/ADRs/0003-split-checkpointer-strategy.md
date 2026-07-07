# ADR-0003: Split checkpointer strategy — AsyncPostgresSaver (ACI) vs MemorySaver (Foundry)

## Status

Accepted

## Context

LangGraph needs a checkpointer for durable state across retries and (eventually) conversation turns. ADR-0002 made Postgres private-VNet-only. Azure AI Foundry Hosted Agent's managed runtime is not inside that VNet and has no network path to a private-only Postgres instance — there is no configuration that lets the Foundry target reach it.

## Decision

`app/checkpointer.py`'s `build_checkpointer()` branches on `FOUNDRY_PROJECT_ENDPOINT`, the same signal `_build_llm()` already uses: unset (ACI) → `AsyncPostgresSaver` against the private Postgres, with a resilience fallback to `MemorySaver` (with a logged warning) if the Postgres extra/env vars aren't actually available — covering bare local dev, not production ACI. Set (Foundry) → `MemorySaver` unconditionally; Foundry's state does not survive a restart on this path.

## Consequences

- The Foundry Hosted Agent target is *not* durable across restarts today — an explicit, accepted gap, tracked in `README.md`'s Open items as "wire a Cosmos DB checkpointer for the Foundry Hosted Agent path."
- The Postgres connection string must URL-encode credentials (`urllib.parse.quote_plus`) since the admin password is an unconstrained Terraform-supplied secret — this was found as a real bug during a final whole-branch review and fixed.
- Local dev without any Postgres configuration (`pip install -e ".[dev]"`, no `DB_*` env vars) must not crash — `build_checkpointer()`'s fallback-to-`MemorySaver`-on-missing-config path exists specifically so the documented local-dev flow keeps working.
