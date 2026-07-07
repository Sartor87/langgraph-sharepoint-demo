import httpx
import pytest
import respx

from app.tools.sharepoint_tool import search_sharepoint


@pytest.mark.asyncio
async def test_search_sharepoint_uses_azure_function_by_default(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_TOOL_BACKEND", raising=False)
    monkeypatch.setenv("SHAREPOINT_FUNCTION_URL", "https://func.example.azurewebsites.net")

    with respx.mock:
        route = respx.post("https://func.example.azurewebsites.net/search").mock(
            return_value=httpx.Response(200, json={"documents": [{"doc_id": "1"}]})
        )
        result = await search_sharepoint(query="q", site_url="https://s.example.com")

    assert route.called
    assert result == [{"doc_id": "1"}]


@pytest.mark.asyncio
async def test_search_sharepoint_python_backend_explicit(monkeypatch):
    monkeypatch.setenv("SHAREPOINT_SERVICE_URL", "https://sidecar.example.com")

    with respx.mock:
        route = respx.post("https://sidecar.example.com/search").mock(
            return_value=httpx.Response(200, json={"documents": [{"doc_id": "2"}]})
        )
        result = await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="python"
        )

    assert route.called
    assert result == [{"doc_id": "2"}]


@pytest.mark.asyncio
async def test_search_sharepoint_raises_when_azure_function_url_unset(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_FUNCTION_URL", raising=False)

    with pytest.raises(NotImplementedError):
        await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="azure_function"
        )


@pytest.mark.asyncio
async def test_search_sharepoint_raises_when_python_url_unset(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_SERVICE_URL", raising=False)

    with pytest.raises(NotImplementedError):
        await search_sharepoint(query="q", site_url="https://s.example.com", backend="python")


@pytest.mark.asyncio
async def test_search_sharepoint_invalid_backend_raises_value_error():
    with pytest.raises(ValueError, match="invalid_backend_name"):
        await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="invalid_backend_name"
        )
