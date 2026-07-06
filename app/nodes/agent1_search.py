"""Agent 1: searches SharePoint for documents matching the current query."""

from __future__ import annotations

import os

from app.schemas.state import AuditState
from app.tools.sharepoint_tool import search_sharepoint

SITE_URL = os.environ.get("SHAREPOINT_SITE_URL", "")


async def agent1_search_sharepoint(state: AuditState) -> dict:
    docs = await search_sharepoint(query=state["query"], site_url=SITE_URL)

    # De-duplicate against docs already collected in prior iterations.
    existing_ids = {d["doc_id"] for d in state.get("sharepoint_docs", [])}
    new_docs = [d for d in docs if d["doc_id"] not in existing_ids]

    return {
        "sharepoint_docs": state.get("sharepoint_docs", []) + new_docs,
        "iteration": state.get("iteration", 0) + 1,
    }
