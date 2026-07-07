# ADR-0007: Fabric MCP context is a graph-wired node, not an LLM tool-calling decision

## Status

Accepted

## Context

Early framing of "the LLM will choose" for SharePoint backend selection (Azure Function vs. the CSOM sidecar explore option) raised the question of whether Agent 4's *existence in the graph* should similarly be something an LLM decides per-turn, via `bind_tools`-style function-calling, versus a fixed part of the compiled graph. `app/nodes/agent1_search.py` and its sibling agents are fixed, deterministic LangGraph nodes with no LLM tool-calling in front of them at all.

## Decision

Two separate things were kept distinct: (1) SharePoint's `backend` parameter (`azure_function` vs `python`) is env-var/config-driven, resolved once per call inside `search_sharepoint()` — never a live LLM decision. (2) Agent 4 itself *is* a real LLM tool-calling step *internally* (it decides which Fabric tools to call, if any, given the task) — but whether Agent 4 *runs at all* is fixed graph wiring (`START` fans out into `agent1` and `agent4` unconditionally, every iteration), not something an LLM opts in or out of.

## Consequences

- `app/nodes/agent1_search.py` required zero changes to support the backend split — the config resolution is entirely inside the tool function, invisible to the deterministic node calling it.
- Agent 4's LLM tool-calling is bounded to one round (one call with tools bound → execute requested calls → one summary call) rather than open-ended ReAct, keeping it consistent with this project's existing `MAX_ITERATIONS`-bounded design philosophy elsewhere in the graph.
- Adding a third SharePoint backend, or making Agent 4 conditional on some future signal, are both structurally cheap changes — the config-driven and graph-driven decision points don't entangle.
