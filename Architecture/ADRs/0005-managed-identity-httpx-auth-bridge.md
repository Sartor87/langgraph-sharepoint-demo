# ADR-0005: Bridge Managed Identity into PnP Core SDK via a custom auth provider, not a built-in one

## Status

Accepted

## Context

The SharePoint Azure Function needed to authenticate to SharePoint using its own Managed Identity (no certificate/secret management). Direct inspection of the real, installed `PnP.Core.Auth` 1.16.0 assembly (reflection over its types, not assumption) showed it has **no built-in Managed Identity provider** — its real provider set is `Certificate`, `CredentialManager`, `DeviceCode`, `External`, `Interactive`, `OnBehalfOf`, `UsernamePassword`, `AspNetCore`.

## Decision

Use `PnP.Core.Auth.ExternalAuthenticationProvider` — PnP Core SDK's documented escape hatch for an arbitrary token-acquisition callback — wired to `Azure.Identity`'s `ManagedIdentityCredential`. The exact callback signature (`Func<Uri, string[], Task<string>>` — confirmed by reflecting over the real assembly, not the shape a first draft assumed) was verified empirically before being written into the implementation plan, avoiding a repeat of the original broken `azure.ai.agentserver.langgraph.from_langgraph` import that motivated the whole Foundry hosting-adapter effort.

## Consequences

- The pattern (verify the real API via reflection before writing implementation code, rather than trusting library documentation or general Azure SDK conventions) directly caught and prevented four separate wrong assumptions during implementation: the callback signature, `SearchOptions`/`ISearchResult`'s real namespace (`PnP.Core.Model.SharePoint`, not `PnP.Core.QueryModel`), the correct DI wiring point (`PnPCoreOptions.DefaultAuthenticationProvider`), and the correct JSON-serialization-options type for the AspNetCore-integrated HTTP hosting model this Function uses.
- The Managed Identity must be granted a SharePoint API permission (`Sites.Selected` or `Sites.Read.All`) via Entra admin consent — a manual, human-run prerequisite, not automated by any Terraform or deploy script yet.
- The same `httpx.Auth`-subclass pattern was reused for the Fabric MCP integration (`FabricManagedIdentityAuth`, ADR-0006/0007's context) once it was confirmed that `langchain-mcp-adapters`' `StreamableHttpConnection` has an analogous `auth: httpx.Auth` extension point.
