# Foundry AI Services — Terraform import

Brings an **already-existing** Azure AI Foundry account + project under
Terraform management. Does not create new resources — the account/project
must already exist in Azure.

## Prerequisites

- The Foundry AI Services account and project already exist in Azure.
- `az login` with access to the target subscription.

## One-time setup

```bash
cd terraform/environments/foundry
export TF_VAR_subscription_id=<your-subscription-id>
export TF_VAR_resource_group_name=<your-resource-group-name>
export TF_VAR_account_name=<your-account-name>
export TF_VAR_custom_subdomain_name=<your-account-custom-subdomain>
export TF_VAR_project_name=<your-project-name>

terraform init
```

## Import the existing resources

```bash
terraform import module.foundry_ai_services.azurerm_cognitive_account.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>

terraform import module.foundry_ai_services.azurerm_cognitive_account_project.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>/projects/<project-name>
```

Find the account's real resource ID with:
```bash
az cognitiveservices account show --name <account-name> --resource-group <resource-group-name> --query id -o tsv
```

## After import

```bash
terraform plan
```

Expected: no changes, or only the intentional corrections this module makes
to the account's exported config (e.g. `network_acls.bypass` moving from
unset/empty to `"AzureServices"` — Azure's real default; the export tool's
empty string isn't a valid value). Any other diff means a variable default
doesn't match the real resource yet — fix the variable value, don't apply
blindly.

```bash
terraform output -raw foundry_project_endpoint
```

This is the value `foundry/README.md` uses for `FOUNDRY_PROJECT_ENDPOINT`.
