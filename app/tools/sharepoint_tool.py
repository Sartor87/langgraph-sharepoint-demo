"""
SharePoint search tool used by Agent 1.

INTEGRATION NOTE
-----------------
Actual document extraction is implemented with CSOM via the PnP Framework,
which is a .NET-only library. This Python process does NOT talk to SharePoint
directly. Instead, it calls a small .NET sidecar/service (planned, not yet
scaffolded here — e.g. `sharepoint-csom-service/`) over HTTP.

Expected sidecar contract (subject to change once the .NET service exists):

    POST {SHAREPOINT_SERVICE_URL}/search
    {
        "query": "string",
        "site_url": "string",
        "max_results": 20
    }
    ->
    {
        "documents": [
            {
                "doc_id": "string",
                "title": "string",
                "url": "string",
                "content_snippet": "string",
                "last_modified": "iso8601",
                "library": "string",
                "metadata": {}
            }
        ]
    }

Until the sidecar exists, `search_sharepoint` raises NotImplementedError so
the gap is loud rather than silently returning empty results.
"""

from __future__ import annotations

import os

import httpx

SHAREPOINT_SERVICE_URL = os.environ.get("SHAREPOINT_SERVICE_URL")


async def search_sharepoint(
    query: str, site_url: str, max_results: int = 20
) -> list[dict]:
    """Call the .NET CSOM/PnP sidecar to search SharePoint.

    Raises:
        NotImplementedError: if SHAREPOINT_SERVICE_URL is not configured,
            i.e. the .NET sidecar has not been wired up yet.
        httpx.HTTPStatusError: on non-2xx response from the sidecar.
    """
    if not SHAREPOINT_SERVICE_URL:
        raise NotImplementedError(
            "SHAREPOINT_SERVICE_URL is not set. The .NET CSOM/PnP Framework "
            "sidecar has not been scaffolded/deployed yet — see the module "
            "docstring for the expected contract."
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SHAREPOINT_SERVICE_URL}/search",
            json={"query": query, "site_url": site_url, "max_results": max_results},
        )
        response.raise_for_status()
        return response.json()["documents"]
