"""httpx.Auth bridging Managed Identity into the Fabric MCP client.

langchain-mcp-adapters' StreamableHttpConnection accepts an `auth: httpx.Auth`
field (confirmed via inspection of the installed langchain-mcp-adapters 0.3.0
package's `sessions.StreamableHttpConnection`) — httpx's own extensible auth
interface, the correct mechanism for a token that must be refreshed per
request rather than supplied once as a static header.
`ManagedIdentityCredential.get_token()` caches and refreshes internally, so
calling it in `async_auth_flow` on every request is correct and cheap.
"""

from __future__ import annotations

import httpx
from azure.identity.aio import ManagedIdentityCredential

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


class FabricManagedIdentityAuth(httpx.Auth):
    """Acquires a Managed Identity token for the Fabric MCP server's scope
    on every request; azure-identity handles caching/refresh internally.
    """

    def __init__(self, credential: ManagedIdentityCredential | None = None) -> None:
        self._credential = credential or ManagedIdentityCredential()

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._credential.get_token(FABRIC_SCOPE)
        request.headers["Authorization"] = f"Bearer {token.token}"
        yield request
