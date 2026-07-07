# ADR-0001: Deploy to ACI and Foundry Hosted Agent as parallel targets, not a migration

## Status

Accepted

## Context

The project needed a production deploy path. Azure Container Instances (ACI) + Application Gateway, provisioned via Terraform, was built first. Azure AI Foundry Hosted Agent support was then requested. `README.md`'s original wording described Foundry as a "future migration" replacing ACI — but the actual work needed the Foundry hosting adapter to be *real* (it previously imported a nonexistent module) regardless of whether ACI stayed.

## Decision

Both targets are permanent, parallel, independently-deployable options — not a migration path. The same container image serves both; `FOUNDRY_PROJECT_ENDPOINT` being set (Foundry-injected) or unset (ACI) is the only branch point, checked in exactly two places: `app/graph.py`'s `_build_llm()` and `app/checkpointer.py`'s `build_checkpointer()`. Neither target's Terraform/infrastructure work retires the other.

## Consequences

- Two live infrastructure stacks to maintain: `terraform/environments/dev` (ACI + App Gateway + private Postgres) and `foundry/` (`azd`-managed Foundry Hosted Agent).
- Every future runtime branch point (LLM client, checkpointer, and now the Fabric MCP context agent's dependency footprint) must be re-examined against both targets — see ADR-0003 for the checkpointer consequence this forced.
- `docker/Dockerfile` and `pyproject.toml`'s dependency set must satisfy both targets simultaneously — a dependency that's genuinely optional for one target but hard-required by the other (e.g. `langchain-mcp-adapters`, since Agent 4 always runs) cannot live in an "optional per-target" extra; it must be a base dependency.

## Alternatives considered

- **AWS Bedrock** as an LLM provider alternative/complement to Azure OpenAI / AI Foundry. The organization also runs AWS infrastructure and is evaluating Bedrock across its projects — not adopted here, since `_build_llm()`'s two branches are both Azure-native (`AzureChatOpenAI` and Foundry's OpenAI-compatible endpoint). A third branch for Bedrock would need its own credential/client story (AWS IAM vs. Managed Identity) and is not currently planned for this project specifically; noted here as live cross-org context, not a decision made or reversed.

