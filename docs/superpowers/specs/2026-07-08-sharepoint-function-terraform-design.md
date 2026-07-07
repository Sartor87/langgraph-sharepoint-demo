# SharePoint Function Terraform Infrastructure — Design

Date: 2026-07-08
Status: Approved (pending spec self-review)

Note: `docs/superpowers/` is gitignored in this repo — this file stays on
disk as the design record but is not committed to git, same treatment as
this project's other specs written this way.

## Context

`sharepoint-csom-service/` (a C# Azure Function using PnP Core SDK, code
complete and building cleanly) has no Terraform. The rest of this project's
infrastructure (ACI, App Gateway, Postgres, Key Vault, ACR, jumpbox) is
fully Terraform-managed; this Function was scaffolded and implemented in
application-code tasks that explicitly deferred its infrastructure ("a
separate future spec/plan," per that work's own plan). This spec is that
deferred piece.

## Scope

In scope:
- New reusable module `terraform/modules/function-app/`: a Linux Azure
  Function App (Consumption plan, `.NET` isolated worker, code-deploy — no
  Dockerfile exists for this Function, so no container image handling) plus
  its required dedicated Storage Account, wired for
  `storage_uses_managed_identity = true` (no stored storage key) via role
  assignments on the identity passed in.
- Wiring in `terraform/environments/dev/main.tf`: a new, dedicated
  `azurerm_user_assigned_identity.sharepoint_function` (separate from the
  existing `audit_agent` identity — least-privilege, since only this
  Function ever needs SharePoint permissions; the ACI container never talks
  to SharePoint directly, only over HTTP to this Function) and an
  instantiation of the new module.
- Documentation of the SharePoint `Sites.Selected` permission grant as an
  entirely manual, human-run prerequisite (both the Graph app-role-assignment
  step and the site-specific scoping step — the latter has no
  `azurerm`/`azuread` Terraform resource at all, so keeping the whole grant
  manual is more consistent than partially automating it).

Out of scope (explicitly deferred):
- Actually deploying the Function's code (`func azure functionapp publish`
  or a CI/CD pipeline step) — Terraform only provisions the infra shell,
  same treatment as this project's other "Terraform builds infra, a
  separate manual/CI step deploys code" pattern (ACR image push via GitHub
  Actions, Foundry deploy via `azd`).
- VNet integration for the Function (not needed — SharePoint Online is a
  public endpoint, and this Function never touches the private-VNet
  Postgres).
- Automating any part of the SharePoint `Sites.Selected` grant via the
  `azuread` provider — considered and explicitly rejected in favor of
  keeping the whole grant manual (see Context).
- A Terraform module for the AWS Lambda hosting alternative mentioned in
  `Architecture/ADRs/0004-sharepoint-azure-function-default.md`'s
  "Alternatives considered" section — that's still an org-wide evaluation,
  not a decision for this project.

## Architecture

```
terraform/modules/function-app/       # NEW, generic (not SharePoint-specific —
│                                     #   reusable if a future MCP server or
│                                     #   other Function lands on Azure)
├── versions.tf                       # azurerm ~> 3.0 — this module is
│                                     #   instantiated from environments/dev,
│                                     #   which is pinned to ~> 3.0; NOT a
│                                     #   separate root like environments/foundry
├── variables.tf                      # name, resource_group_name, location,
│                                     #   tags, identity_id (UAI resource ID,
│                                     #   required — caller creates the
│                                     #   identity, mirroring how container-group
│                                     #   takes identity_id rather than creating
│                                     #   its own), dotnet_version (default "10.0")
├── main.tf                           # azurerm_storage_account (dedicated) +
│                                     #   azurerm_service_plan (SKU "Y1",
│                                     #   Consumption) + azurerm_linux_function_app
│                                     #   (dotnet-isolated, storage_uses_managed_identity
│                                     #   = true) + azurerm_role_assignment
│                                     #   (Storage Blob/Queue/Table Data
│                                     #   Owner, scoped to the storage account,
│                                     #   for the passed-in identity)
└── outputs.tf                        # function_app_id, default_hostname

terraform/environments/dev/main.tf    # MODIFY: new
                                       #   azurerm_user_assigned_identity.sharepoint_function
                                       #   (separate from audit_agent's identity)
                                       #   + module "sharepoint_function" instantiation
```

## Identity and permissions

- **Dedicated identity, not reused.** `audit_agent`'s existing identity is
  used for ACR pull and Key Vault `Get` — neither of which the SharePoint
  Function needs, and the Function needs SharePoint `Sites.Selected` access,
  which the ACI container never needs (Agent 1 only ever talks to this
  Function over HTTP, never to SharePoint directly). Sharing one identity
  would mean the ACI container's compute could, in principle, request tokens
  scoped to permissions it structurally has no reason to hold.
- **Storage access via role assignment, not a stored key.** `azurerm_linux_function_app`
  supports `storage_uses_managed_identity = true`, avoiding
  `storage_account_access_key` entirely — one fewer secret to manage,
  consistent with this project's existing preference for Managed Identity
  over stored credentials everywhere else (SharePoint's own PnP Core SDK
  auth, Fabric MCP auth).
- **The SharePoint `Sites.Selected` grant stays entirely manual.** It has two
  parts: (1) a Microsoft Graph application-permission grant
  (`Sites.Selected`) to the identity's service principal — technically
  automatable via the `azuread` provider's `azuread_app_role_assignment`;
  (2) site-specific scoping (which SharePoint site collection the grant
  actually applies to) via a Graph API call
  (`POST /sites/{site-id}/permissions`) that has no Terraform resource at
  all. Since part 2 can never be automated with the tools this project uses,
  automating only part 1 would be inconsistent (half-automated, half-manual,
  for one logically single grant) — the whole grant is documented as one
  manual prerequisite instead, consistent with how this project already
  treats the Fabric MCP Managed Identity's permission grant.

## Documentation

- `sharepoint-csom-service/README.md` gains the exact manual grant steps
  (Graph app-role-assignment + site-specific scoping, with real Graph API
  call shapes) once the identity exists via Terraform to reference by name.
- `terraform/README.md` or `terraform/environments/dev/README.md` (whichever
  already documents this environment's other manual prerequisites) gets a
  pointer to the same steps, so a deployer sees it from either direction.

## Open questions

None — all scope/design decisions (generic module naming/location, dedicated
identity, Consumption plan, managed-identity storage access, keeping the
whole SharePoint permission grant manual) were confirmed with the user
during brainstorming.
