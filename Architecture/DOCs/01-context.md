# Level 1 — System Context — SharePoint Audit Agent

> **Diagram type**: System Context
> **Scope**: The SharePoint Audit Agent system as a whole, and the people/external systems it interacts with.
> **Audience**: Everyone — technical and non-technical.

## Overview

The SharePoint Audit Agent is a multi-agent LangGraph workflow that audits SharePoint document libraries for compliance, producing a traceable audit trail (EU AI Act Annex III). A Compliance Officer submits an audit request; the system searches SharePoint, evaluates whether the retrieved evidence is sufficient, optionally enriches the result with read-only context from Microsoft Fabric, and finalizes a report. This diagram shows the system as one box, plus the people and external systems around it — the detail of what's inside is the Container diagram (`02-container.md`).

## Diagram

Rendered from `Architecture/workspace.dsl`, view key `SystemContext`. Render via Structurizr Lite/CLI, or the [Structurizr web renderer](https://structurizr.com) pointed at the workspace file.

## Legend

- **Person**: human user of the system (Compliance Officer)
- **System (in scope)**: the SharePoint Audit Agent itself
- **External System**: SharePoint Online, Azure OpenAI/AI Foundry, Microsoft Fabric MCP Server — all out of scope, owned by Microsoft, consumed by the Audit Agent

## Elements

| Element | Type | Technology | Responsibility |
|---|---|---|---|
| Compliance Officer | Person | — | Submits audit requests, reviews reports |
| SharePoint Audit Agent | System (in scope) | — | Multi-agent audit workflow (this system) |
| SharePoint Online | External System | Microsoft 365 | The document libraries being audited |
| Azure OpenAI / AI Foundry | External System | Azure-hosted LLM | Provides completions to all four agents |
| Microsoft Fabric MCP Server | External System | Remote MCP server | Read-only Fabric catalog/workspace context |

## Key relationships

| From | To | Intent | Protocol / Technology |
|---|---|---|---|
| Compliance Officer | SharePoint Audit Agent | Submits audit requests to, and reviews reports from | HTTPS/JSON (Responses API or `/invoke`) |
| SharePoint Audit Agent | SharePoint Online | Queries document libraries from (via the SharePoint Search Function — see Container diagram) | PnP Core SDK over REST, Managed Identity auth |
| SharePoint Audit Agent | Azure OpenAI / AI Foundry | Generates completions via | HTTPS/JSON |
| SharePoint Audit Agent | Microsoft Fabric MCP Server | Queries read-only context via (degrades gracefully on failure) | MCP over HTTPS (streamable_http), Managed Identity auth |

## Notable architectural decisions

- **Fabric MCP is explicitly read-only and fails open.** Agent 4 (the node that talks to Fabric) is restricted to a fixed read-only tool allowlist — no create/update/delete/role operations — as a deliberate compliance boundary, since this system's core purpose is auditing, not modifying, external systems. Any Fabric failure degrades to a note in the audit trail rather than aborting the primary SharePoint audit.
- **Two deploy targets, one system.** The same container image runs on Azure Container Instances and as an Azure AI Foundry Hosted Agent — this is a Container-level/deployment detail, invisible at the Context level, where both targets are the same "SharePoint Audit Agent" box.

## Assumptions

- The "Compliance Officer" persona is inferred from the project's stated EU AI Act Annex III traceability goal (`README.md`) — no other actor/persona was specified, so this is the only Person modeled. If other consumers exist (e.g. an automated scheduler triggering audits on a cron), they aren't represented here.
- Azure OpenAI and Azure AI Foundry's model endpoint are modeled as one External System ("Azure OpenAI / AI Foundry") since the Audit Agent talks to functionally the same completions API either way (`app/graph.py`'s `_build_llm()` branches between them, but the external system being called is conceptually one thing from the Context view).

## Links to other levels

- ↓ [Container diagram](./02-container.md) — zoom into the SharePoint Audit Agent system
- See also: [`../ADRs/`](../ADRs/) — decision records behind the choices shown here
