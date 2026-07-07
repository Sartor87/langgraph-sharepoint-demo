# SharePoint Azure Function Search Tool — Design

Date: 2026-07-07
Status: Approved (pending spec self-review)

## Context

`app/tools/sharepoint_tool.py` is currently an unimplemented stub: `search_sharepoint()` raises `NotImplementedError` unless `SHAREPOINT_SERVICE_URL` is set, expecting an HTTP call to a planned-but-never-scaffolded ".NET CSOM/PnP Framework sidecar" (`sharepoint-csom-service/`, per the module docstring and `README.md`'s Open items).

This spec adds a real implementation of that sidecar as a C# Azure Function using PnP Core SDK's Search feature (`context.Web.SearchAsync`, per Microsoft's PnP Core SDK docs — not raw CSOM, and not the classic PnP Framework), authenticating via the Function's Managed Identity. The existing Python-side stub is kept as a second, explicitly "explore" option — not removed, not required to be finished — selectable via a config-driven `backend` parameter.

## Scope

In scope:
- New C# Azure Function project, `sharepoint-csom-service/`, exposing `POST /search` (`routePrefix` set to empty so the route is exactly `/search`, no `/api` prefix), implemented with PnP Core SDK, authenticating via Managed Identity.
- Response/request contract identical to the existing Python stub's documented contract (`query`/`site_url`/`max_results` → `documents: [{doc_id, title, url, content_snippet, last_modified, library, metadata}]`) — this is what lets both backends be interchangeable behind one Python function.
- `app/tools/sharepoint_tool.py`: add a `backend` parameter to `search_sharepoint()`, defaulting from a new `SHAREPOINT_TOOL_BACKEND` env var (default `"azure_function"`), routing to either the new Azure Function (`SHAREPOINT_FUNCTION_URL`) or the existing stub path (`SHAREPOINT_SERVICE_URL`, unchanged behavior — still raises `NotImplementedError` if unset).
- `sharepoint-csom-service/README.md`: local dev (Azure Functions Core Tools), deployment notes, and an explicit note that AWS Lambda is a valid alternative hosting target for this same PnP Core SDK code in AWS-hosted deployments (documentation only — no Lambda implementation).
- `README.md`'s "SharePoint access" design bullet updated to describe both backends.

Out of scope (explicitly deferred):
- Any Terraform/infrastructure for deploying the Function App (Function App resource, Managed Identity role assignment, VNet integration if needed) — a separate future spec/plan, same treatment as this repo's other "real Azure resources" work (manual/human-run until then).
- Converting Agent 1 (`app/nodes/agent1_search.py`) into an LLM tool-calling step — it stays a fixed, deterministic LangGraph node calling `search_sharepoint()` directly. The `backend` selection is config/env-var driven (fixed per deployment), not a live per-call LLM decision — "the LLM picks a backend" in casual conversation meant "the system uses whichever backend is configured," not `bind_tools`-style function-calling.
- An actual AWS Lambda implementation — documentation-only mention that the same PnP Core SDK code is portable to Lambda for AWS-hosted deployments.
- Full document content retrieval beyond the search result's snippet (`content_snippet` stays a search hit highlight/summary, matching the existing contract — no separate "fetch full document body" operation).

## Architecture

```
sharepoint-csom-service/
├── SharePointSearchFunction.csproj
├── host.json                        # "extensions": { "http": { "routePrefix": "" } }
│                                     #   — makes the route exactly /search, matching the
│                                     #   Python stub's contract (no /api prefix)
├── local.settings.json.example      # local dev config template — placeholders only,
│                                     #   no real tenant/site/credential values (this repo
│                                     #   is public)
├── Program.cs                       # Azure Functions isolated-worker host builder;
│                                     #   registers PnP Core SDK (AddPnPCore) with a
│                                     #   Managed Identity authentication provider
├── Functions/
│   └── SearchFunction.cs            # [Function("Search")], HttpTrigger POST, route "search"
├── Models/
│   ├── SearchRequest.cs             # query (string), site_url (string), max_results (int)
│   ├── SearchResponse.cs            # documents (List<DocumentResult>)
│   └── DocumentResult.cs            # doc_id, title, url, content_snippet, last_modified,
│                                     #   library, metadata (Dictionary<string, object>)
└── README.md                        # local dev, deploy notes, AWS Lambda alternative note
```

`app/tools/sharepoint_tool.py` gains a `backend` parameter and a second base-URL env var, but keeps one shared HTTP-calling code path for both backends (see "Python-side routing" below) — the whole point of matching contracts is that the caller doesn't need backend-specific branching beyond picking a URL.

`app/nodes/agent1_search.py` is **unchanged** — it already just calls `search_sharepoint(query=..., site_url=...)`; backend resolution happens inside the tool function via the env var default, so the deterministic graph node doesn't need to know backends exist.

## PnP Core SDK search execution & field mapping

- **Auth**: the Function authenticates to SharePoint via its Azure **Managed Identity**, using PnP Core SDK's managed-identity authentication provider. The exact provider class/configuration API is an **implementation-time discovery item** — it must be confirmed against the actually-installed PnP Core SDK NuGet package version, not assumed from general documentation (same "verify against the real package" discipline this project applied to `langchain_azure_ai.agents.hosting` earlier). The behavior contract is fixed regardless of the exact API: no certificate or client-secret management, the Function's own Managed Identity is what SharePoint sees. The Managed Identity must be granted a SharePoint API permission (`Sites.Selected` or `Sites.Read.All`) — a manual, human-run prerequisite (Entra admin consent), documented in `sharepoint-csom-service/README.md`, not automated by this spec's implementation (infra/permissions grants are the deferred Terraform work).
- **Search call**: `PnPContextFactory` builds a `PnPContext` for the request's `site_url`; `SearchOptions(query)` with `TrimDuplicates = false`, `RowLimit = max_results`, and a `SelectProperties` list covering the managed properties needed for the field mapping below.
- **Field mapping** (search result row → `DocumentResult`), also an implementation-time discovery item for the exact managed property names available on the real tenant's search schema, with this intended mapping as the target:
  - `doc_id` ← a unique-identifier managed property (`UniqueId` or `DocId`)
  - `title` ← `Title`
  - `url` ← `Path`
  - `content_snippet` ← `HitHighlightedSummary`
  - `last_modified` ← `LastModifiedTime`
  - `library` ← parsed from `Path`, or a dedicated managed property if the tenant's search schema exposes one
  - `metadata` ← the remaining raw result-row properties, as a dictionary

## Python-side routing

- New env var `SHAREPOINT_FUNCTION_URL` (Azure Function base URL), alongside the existing `SHAREPOINT_SERVICE_URL` (.NET sidecar path, kept as the "explore" option).
- New env var `SHAREPOINT_TOOL_BACKEND`, default `"azure_function"`.
- `search_sharepoint(query: str, site_url: str, max_results: int = 20, backend: str | None = None) -> list[dict]`:
  - `backend` defaults to `os.environ.get("SHAREPOINT_TOOL_BACKEND", "azure_function")` when not explicitly passed.
  - `backend == "azure_function"` → POST to `{SHAREPOINT_FUNCTION_URL}/search`; raises `NotImplementedError` if `SHAREPOINT_FUNCTION_URL` is unset (mirroring the existing stub's "loud gap" philosophy — this backend isn't deployed yet either, until the deferred infra work lands).
  - `backend == "python"` → POST to `{SHAREPOINT_SERVICE_URL}/search`, entirely unchanged from current behavior (still `NotImplementedError` if unset).
  - Any other `backend` value → `ValueError` naming the invalid value and the two valid options.
  - Both branches share one internal HTTP-calling helper (same request/response shape, same error handling) — no per-backend duplication.

## Documentation

- `sharepoint-csom-service/README.md`: prerequisites (Managed Identity + SharePoint API permission grant, Azure Functions Core Tools for local dev), `func start` instructions, deployment notes (pointing at the deferred Terraform work once it exists), and an explicit "AWS Lambda alternative" section noting this PnP Core SDK code is portable to a Lambda function for AWS-hosted deployments of this project (documentation only, no Lambda code).
- `README.md`'s "SharePoint access" bullet (`Key design decisions`) updated to describe both backends: Azure Function (PnP Core SDK, Managed Identity) as the primary path, the .NET CSOM/PnP Framework sidecar stub as a config-selectable "explore" alternative, selected via `SHAREPOINT_TOOL_BACKEND`.

## Open questions

None — all scope/design decisions (PnP Core SDK vs raw CSOM, single-tool-with-parameter vs two tools, contract parity, Managed Identity auth, infra deferred, file location, config-driven not LLM-tool-calling-driven backend selection) were confirmed with the user during brainstorming.
