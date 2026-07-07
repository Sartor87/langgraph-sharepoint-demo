# Level 2 — Container — SharePoint Audit Agent

> **Diagram type**: Container
> **Scope**: Inside the SharePoint Audit Agent system — its independently deployable pieces and their datastores.
> **Audience**: Technical team (dev, ops, architecture).

## Overview

The SharePoint Audit Agent is a Python/LangGraph application (the "Audit Agent" container) that never talks to SharePoint directly — it delegates to a separate C# Azure Function that wraps SharePoint's PnP Core SDK. The Audit Agent's own state is durable only on its Azure Container Instances (ACI) deploy target, backed by a private Postgres database reachable exclusively through the VNet or an admin jumpbox; its Azure AI Foundry Hosted Agent deploy target keeps state in memory instead, since Foundry's managed runtime has no path into that private network. Both deploy targets are the *same* container image, pulled from a shared Container Registry.

## Diagram

Rendered from `Architecture/workspace.dsl`, view key `Containers`. Render via Structurizr Lite/CLI, or the [Structurizr web renderer](https://structurizr.com) pointed at the workspace file.

## Legend

- **Container**: independently deployable application or data store
- **Container, Database** (cylinder shape in the DSL styles): a datastore container
- **External System**: out-of-scope system — see the Context diagram (`01-context.md`) for these

## Elements

| Element | Type | Technology | Responsibility |
|---|---|---|---|
| Audit Agent | Container | Python, LangGraph, FastAPI / Foundry Responses protocol host, Docker | Runs the 4-agent audit workflow; same image on both deploy targets |
| SharePoint Search Function | Container | C#, Azure Functions (isolated worker), PnP Core SDK | Searches/finds SharePoint documents on the Audit Agent's behalf |
| Checkpoint Database | Container, Database | Azure Database for PostgreSQL Flexible Server 16 | Durable LangGraph checkpoint storage — ACI target only |
| Secrets Store | Container | Azure Key Vault | Holds the Audit Agent's runtime secrets |
| Container Registry | Container | Azure Container Registry | Stores the built image both deploy targets pull from |
| Admin Jumpbox | Container | Ubuntu 22.04, Azure VM | SSH bastion for direct admin access to the Checkpoint Database |
| Observability | Container | Azure Application Insights / Log Analytics | Telemetry/log sink for the Audit Agent and the SharePoint Search Function |

## Key relationships

| From | To | Intent | Protocol / Technology |
|---|---|---|---|
| Compliance Officer | Audit Agent | Submits audit requests to, and reviews reports from | HTTPS/JSON (Responses API or `/invoke`) |
| Audit Agent | SharePoint Search Function | Searches documents and finds files via | HTTPS/JSON |
| SharePoint Search Function | SharePoint Online | Queries document libraries from | PnP Core SDK over REST, Managed Identity auth |
| Audit Agent | Checkpoint Database | Persists LangGraph checkpoints to (ACI target only) | PostgreSQL wire protocol over TLS |
| Audit Agent | Secrets Store | Reads runtime secrets from | HTTPS/REST, Managed Identity auth |
| Audit Agent | Azure OpenAI / AI Foundry | Generates completions via | HTTPS/JSON |
| Audit Agent | Microsoft Fabric MCP Server | Queries read-only Fabric context via (degrades gracefully on failure) | MCP over HTTPS (streamable_http), Managed Identity auth |
| Audit Agent | Container Registry | Pulls its container image from | Docker Registry API over HTTPS (deploy time) |
| Admin Jumpbox | Checkpoint Database | Forwards an admin SSH tunnel to | TCP port-forward over SSH |
| Audit Agent | Observability | Sends telemetry and logs to | HTTPS / OpenTelemetry |
| SharePoint Search Function | Observability | Sends telemetry and logs to | HTTPS / OpenTelemetry |

## Notable architectural decisions

- **One "Audit Agent" container, two deploy targets.** Rather than modeling ACI and Foundry as two separate Containers, this diagram treats them as one Container — they're the same image, same code, same behavior, differing only in which environment variable (`FOUNDRY_PROJECT_ENDPOINT`) is set at runtime. The deploy-target split (and the infrastructure specific to each — Application Gateway for ACI, `azd`-managed hosting for Foundry) is deployment topology, not application architecture; it belongs in a C4 **Deployment** diagram if one is wanted later, not duplicated here.
- **Checkpoint Database asymmetry is deliberate, not an oversight.** The Foundry deploy target cannot reach the private-VNet-only Postgres, so it uses an in-memory checkpointer instead — a known, accepted non-durability gap for that path (tracked as a TODO in `README.md`'s Open items: a Cosmos DB checkpointer for Foundry).
- **SharePoint access goes through a dedicated Function, not a library call**, because the primary/default implementation uses PnP Core SDK (a .NET-only SDK) — the Python Audit Agent calls it over HTTP instead of embedding .NET. A second, still-unimplemented "explore" backend (a raw CSOM/PnP Framework sidecar) is config-selectable but out of scope for this diagram (it doesn't exist as a running container yet).
- **Fabric MCP access is read-only and fails open** (see `01-context.md`) — reinforced at this level: an unreachable or erroring Fabric MCP Server degrades the Audit Agent's own output (an error note in `fabric_context`) rather than the Audit Agent failing as a Container.

## Assumptions

- **Admin Jumpbox and Container Registry are included here as explicit user choice.** Both are arguably operational/CI-CD concerns rather than runtime application dependencies (the Jumpbox is an admin access path exercised only during manual maintenance; the Registry is only touched at deploy time, not during a live audit request). They're modeled as Containers per explicit instruction during this diagram's framing dialogue, not because they participate in a live audit request's data flow.
- **Observability (Application Insights) is modeled as one shared Container** even though, in the real Terraform, it's one Application Insights resource fed by both the Audit Agent and the SharePoint Search Function independently — no direct relationship exists between the two Containers themselves; they each report to Observability separately.
- **No relationship is drawn from the SharePoint Search Function to the Secrets Store or Container Registry.** Its own Managed Identity and deployment are out of this repo's current Terraform scope (the Function's infrastructure — Function App resource, Managed Identity role assignment — is documented as a deferred, not-yet-built piece of work in `sharepoint-csom-service/README.md`), so no such relationship is asserted.

## Links to other levels

- ↑ [Context diagram](./01-context.md) — the system as one box, with people and external systems
- *Component level not produced — the golden rule (Context + Container suffice for most teams) was applied; revisit only if a Container here (most likely the Audit Agent, with its 4 LangGraph nodes) needs its own Component diagram later.*
- See also: [`../ADRs/`](../ADRs/) — decision records behind the choices shown here (deploy targets, checkpointer split, SharePoint backend, Fabric MCP boundaries, Key Vault mode, Terraform root split)
