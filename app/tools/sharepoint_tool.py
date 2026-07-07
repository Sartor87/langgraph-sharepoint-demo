"""
SharePoint search tool used by Agent 1.

Two interchangeable backends, both implementing the same HTTP contract
(POST {base_url}/search -> {"documents": [...]})  — selected via the
`backend` parameter, defaulting from SHAREPOINT_TOOL_BACKEND (not an LLM
tool-calling decision; app/nodes/agent1_search.py calls this function
directly and never passes `backend`, so it always gets the env-var
default):

  "azure_function" (default) — sharepoint-csom-service/, a real C# Azure
      Function using PnP Core SDK, authenticated via Managed Identity.
  "python" — the original planned .NET CSOM/PnP Framework sidecar. Kept as
      an "explore" option; still unimplemented (SHAREPOINT_SERVICE_URL
      unset raises NotImplementedError, same as before this change).

Request:  {"query": "string", "site_url": "string", "max_results": 20}
Response: {"documents": [{"doc_id", "title", "url", "content_snippet",
                           "last_modified", "library", "metadata"}]}
"""

from __future__ import annotations

import os

import httpx

_VALID_BACKENDS = ("python", "azure_function")


async def _post_search(base_url: str, query: str, site_url: str, max_results: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/search",
            json={"query": query, "site_url": site_url, "max_results": max_results},
        )
        response.raise_for_status()
        return response.json()["documents"]


async def search_sharepoint(
    query: str,
    site_url: str,
    max_results: int = 20,
    backend: str | None = None,
) -> list[dict]:
    """Search SharePoint via one of two interchangeable backends.

    Raises:
        ValueError: if `backend` isn't "python" or "azure_function".
        NotImplementedError: if the selected backend's URL env var isn't set.
        httpx.HTTPStatusError: on non-2xx response from the backend.
    """
    if backend is None:
        backend = os.environ.get("SHAREPOINT_TOOL_BACKEND", "azure_function")

    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"invalid_backend_name: {backend!r} is not a valid SharePoint tool "
            f"backend — must be one of {_VALID_BACKENDS}"
        )

    if backend == "azure_function":
        function_url = os.environ.get("SHAREPOINT_FUNCTION_URL")
        if not function_url:
            raise NotImplementedError(
                "SHAREPOINT_FUNCTION_URL is not set. The sharepoint-csom-service "
                "Azure Function has not been deployed yet."
            )
        return await _post_search(function_url, query, site_url, max_results)

    service_url = os.environ.get("SHAREPOINT_SERVICE_URL")
    if not service_url:
        raise NotImplementedError(
            "SHAREPOINT_SERVICE_URL is not set. The .NET CSOM/PnP Framework "
            "sidecar has not been scaffolded/deployed yet — this is the "
            "'python' backend, kept as an explore option."
        )
    return await _post_search(service_url, query, site_url, max_results)
