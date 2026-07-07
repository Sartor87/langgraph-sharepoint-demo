# ADR-0004: SharePoint access defaults to a C# Azure Function (PnP Core SDK), not the planned .NET CSOM sidecar

## Status

Accepted

## Context

The original design called for a ".NET CSOM/PnP Framework sidecar" that Agent 1 would call over HTTP — CSOM being .NET-only, unusable directly from Python. That sidecar was never scaffolded; `search_sharepoint()` was a stub that always raised `NotImplementedError`. When implementation work started, PnP Core SDK (a modern, actively-maintained .NET SDK for SharePoint/M365, distinct from the older PnP Framework/raw CSOM) was chosen over raw CSOM, based on user-supplied Microsoft documentation covering its Search and Files APIs.

## Decision

`sharepoint-csom-service/` (name kept for continuity with the original placeholder) is a real C# Azure Function (isolated worker, PnP Core SDK) exposing `POST /search` and `POST /files/find`. It's the default backend (`SHAREPOINT_TOOL_BACKEND=azure_function`). The original CSOM/PnP Framework sidecar concept is kept as a second, still-unimplemented, config-selectable "explore" option (`SHAREPOINT_TOOL_BACKEND=python`) — not deleted, since it may still be worth exploring later, but no longer the primary path.

## Consequences

- Both backends share one HTTP contract (`{query, site_url, max_results} -> {documents: [...]}` for search; `{library, file_name_pattern, site_url} -> {files: [...]}` for file lookup), so `app/tools/sharepoint_tool.py` has one shared HTTP-calling helper per operation regardless of which backend is selected.
- `sharepoint-csom-service/`'s actual deployment (Function App resource, Managed Identity role assignment) is explicitly deferred — this ADR covers the code existing and working locally, not it being live in Azure yet.
- The Function's route is `/search` and `/files/find` with no `/api` prefix (`host.json`'s `routePrefix` set to empty) specifically to keep contract parity with the pre-existing stub's calling convention.

## Alternatives considered

- **AWS Lambda as the hosting target for MCP servers.** The organization is evaluating, per project, whether new MCP servers (e.g. the still-deferred "wrap SharePoint tool as an MCP server" migration in `README.md`'s Open items) should run on AWS Lambda rather than Azure Functions, depending on which project/infrastructure they attach to. Not adopted for `sharepoint-csom-service/` itself — it's an Azure Function because this project's identity/auth story (Managed Identity, see ADR-0005) and the rest of its infrastructure (Terraform on Azure) are Azure-native. `sharepoint-csom-service/README.md` already documents that the PnP Core SDK search logic itself is portable to a Lambda handler if an AWS-hosted deployment of this project is ever built — that note predates this ADR and is restated here for visibility.
- **AWS S3 + a vector store** as an alternative document storage/retrieval layer to searching SharePoint directly. The organization has S3 + vector-search infrastructure in other projects and is assessing fit here too. Not adopted: this project's scope is auditing documents *in place* in SharePoint (provenance/traceability matters for the EU AI Act Annex III goal — see ADR-0006's read-only rationale, which applies to the same compliance concern), not re-indexing them into a separate store. Revisiting this would be a significant scope change, not a swap-in alternative.
