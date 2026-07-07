# ADR-0006: Fabric MCP tool access is restricted to a fixed read-only allowlist

## Status

Accepted

## Context

Microsoft Fabric's remote MCP server exposes ~27 tools spanning workspace/item/folder management, including mutating operations (`create_workspace`, `delete_item`, `add_workspace_role`, permission changes) and long-running-operation helpers. Agent 4 was added to pull in *additional context* for an audit — not to manage Fabric. This project also tracks EU AI Act Annex III traceability requirements for its core audit function.

## Decision

Only 10 explicitly-named read-only tools are ever bound to the LLM: `search_catalog`, `list_workspaces`, `get_workspace`, `list_items`, `get_item`, `get_item_definition`, `list_folders`, `get_folder`, `list_capacities`, `get_knowledge`. `filter_read_only_tools()` is applied before `bind_tools()` is ever called — there is no code path that binds the full, unfiltered tool list.

## Consequences

- An automated audit-context step can never mutate the data platform it's reading from, by construction — not by relying on the LLM's judgment or a prompt instruction alone.
- The allowlist was built from Microsoft's published tool names, not verified against a live Fabric MCP server (no tenant was available during implementation) — if the real server namespaces/prefixes tool names differently, Agent 4 silently returns empty `fabric_context` on every run. Tracked as a `README.md` Open item, not resolved by this decision.
- Get_operation_state/get_operation_result (for tracking long-running mutating operations) were excluded as a direct consequence — they only matter for operations this allowlist never triggers.
