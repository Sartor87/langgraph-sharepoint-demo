from unittest.mock import AsyncMock

import httpx
import pytest
from azure.core.credentials import AccessToken

from app.tools.fabric_auth import FABRIC_SCOPE, FabricManagedIdentityAuth


@pytest.mark.asyncio
async def test_async_auth_flow_sets_bearer_header_from_managed_identity_token():
    mock_credential = AsyncMock()
    mock_credential.get_token.return_value = AccessToken("fake-token-value", 9999999999)

    auth = FabricManagedIdentityAuth(credential=mock_credential)
    request = httpx.Request("POST", "https://api.fabric.microsoft.com/v1/mcp/core")

    flow = auth.async_auth_flow(request)
    yielded_request = await flow.__anext__()

    assert yielded_request.headers["Authorization"] == "Bearer fake-token-value"
    mock_credential.get_token.assert_awaited_once_with(FABRIC_SCOPE)


@pytest.mark.asyncio
async def test_default_credential_is_managed_identity_credential():
    from azure.identity.aio import ManagedIdentityCredential

    auth = FabricManagedIdentityAuth()
    assert isinstance(auth._credential, ManagedIdentityCredential)
