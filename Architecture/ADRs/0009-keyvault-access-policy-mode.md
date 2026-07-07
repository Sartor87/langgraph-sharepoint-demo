# ADR-0009: Key Vault uses access-policy mode, not Azure RBAC

## Status

Accepted

## Context

Azure Key Vault supports two authorization models: the legacy access-policy model (per-vault policies naming an identity and its allowed operations) and Azure RBAC (role assignments scoped via Azure's general IAM system, the direction Microsoft recommends for new vaults). This project's Terraform IaC design mirrored an internal reference pattern that used access-policy mode.

## Decision

`terraform/modules/keyvault/` uses access-policy mode (`enable_rbac_authorization` left at its default/unset, two `access_policy` blocks: the Terraform caller gets full secret permissions, the Audit Agent's Managed Identity gets `Get` only).

## Consequences

- Adding a new consumer of Key Vault secrets (e.g. the SharePoint Function, once its infrastructure is built) means adding another explicit `access_policy` block to the module, not a generic role assignment — slightly more Terraform code per new consumer than RBAC mode would need, but keeps permissions visible in one place (the vault resource itself) rather than scattered across `azurerm_role_assignment` resources elsewhere.
- This vault cannot currently use Azure RBAC's more granular built-in roles (e.g. `Key Vault Secrets User` scoped to a specific secret) — access-policy mode's permissions are vault-wide per identity, not per-secret.
- Revisiting this to RBAC mode later is a real migration (Azure requires switching the whole vault's authorization model, not a per-policy toggle) — not a decision to casually reverse.
