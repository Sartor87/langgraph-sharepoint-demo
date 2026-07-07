# ADR-0002: Postgres is private-VNet-only, reachable via jumpbox tunnel, not public+firewall

## Status

Accepted (supersedes an earlier decision in the same project)

## Context

The initial Terraform IaC design (based on a reference project pattern) put Postgres on public network access with a firewall allowlist (`AllowDevIp`, `AllowAzureServices`). This resolved an internal contradiction in the reference pattern (private-only + firewall rules is self-contradictory), but still exposed a public endpoint. The requirement changed: a real VNet with the jumpbox serving as the actual admin access path for Postgres setup and local-machine connections, not a public endpoint with an IP allowlist.

## Decision

Postgres uses `public_network_access_enabled = false`, VNet-integrated via a delegated subnet (`Microsoft.DBforPostgreSQL/flexibleServers`) and a private DNS zone. The only paths in are: the ACI container (same VNet, NSG-allowed on 5432) and the jumpbox VM (SSH bastion, NSG-allowed on 22 from a configured dev IP). A human reaches Postgres by opening an SSH local port-forward through the jumpbox first, then connecting `psql` to `localhost`.

## Consequences

- The previously-built public+firewall NSG rule (`AllowFromLocal` on the Postgres NSG) became genuinely dead code once this shipped — a public IP cannot route to a private VNet subnet regardless of NSG rules — and was removed.
- Foundry Hosted Agent's managed runtime, which is *not* inside this VNet, lost any path to this Postgres instance — this directly forced ADR-0003 (split checkpointer strategy).
- `README.md` gained a "Connecting to Postgres (jumpbox tunnel)" section with the exact SSH port-forward + `psql` commands, since this is now the only way to reach the database directly.
