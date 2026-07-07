# ADR-0010: Foundry AI Services import gets its own Terraform root, resource group stays a data source

## Status

Accepted

## Context

An existing (manually-created) Azure AI Foundry account + project needed to come under Terraform management via `terraform import`, not re-creation. It lives in a resource group not owned by this repo's other Terraform, and `azurerm_cognitive_account_project` requires provider `~> 4.0`, while `terraform/environments/dev` and its modules are pinned to `~> 3.0`.

## Decision

A fully separate root, `terraform/environments/foundry/` (own state file `foundry.tfstate`, same storage backend, own `azurerm ~> 4.0` provider constraint — no conflict since it's a distinct `terraform init`). The target resource group is referenced via `data "azurerm_resource_group"` only — never imported or created as a managed resource, so this Terraform can never modify or destroy a group that may contain other, unrelated resources.

## Consequences

- Two different `azurerm` provider versions coexist in this repo's Terraform, cleanly, because they're in separate roots — this is fine and doesn't need reconciling.
- Importing the account/project is a manual, human-run `terraform import` (two commands, documented with placeholder syntax since this repo is public) — never automated, same treatment as `terraform apply`/`azd deploy` elsewhere in this project.
- No subscription ID, resource group name, account name, or project name is committed anywhere — all five identifying variables are required with no defaults, enforced during both task-level and whole-branch review (this was a mid-brainstorm correction after an early spec draft leaked a real subscription ID, caught before the plan was even written).
