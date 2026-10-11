"""Comprehensive Test Suite for ARDS Core Engine, Models, and REST API."""

import pytest
from httpx import AsyncClient, ASGITransport

from ards.models import ResourceRegistration, ResourceType
from ards.registry import Registry
from ards.server.app import app


def test_registry_search_and_filter():
    reg = Registry()
    reg.register(ResourceRegistration(
        id="tokyo-node",
        type=ResourceType.AGENT,
        name="Tokyo Logistics Agent",
        description="APAC warehouse inventory node",
        endpoint="http://localhost:8001/a2a",
        tags=["tokyo", "inventory"],
        location="Tokyo",
    ))
    reg.register(ResourceRegistration(
        id="mcp-tokyo",
        type=ResourceType.MCP,
        name="Tokyo MCP DB",
        description="Read only warehouse database driver",
        endpoint="http://localhost:8001/mcp",
        tags=["database", "mcp"],
        location="Tokyo",
    ))

    # Test search by query
    res = reg.search(query="Tokyo")
    assert res.total_results >= 2

    # Test filter by type
    res_mcp = reg.search(query="Tokyo", type_filter=ResourceType.MCP)
    assert res_mcp.total_results >= 1
    assert all(r.type == ResourceType.MCP for r in res_mcp.results)


@pytest.mark.asyncio
async def test_ards_web_and_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Search page HTML
        html_resp = await client.get("/?q=Tokyo")
        assert html_resp.status_code == 200
        assert "ARDS" in html_resp.text
        assert "Tokyo" in html_resp.text

        # API Search JSON
        api_resp = await client.get("/api/v1/search?q=warehouse")
        assert api_resp.status_code == 200
        data = api_resp.json()
        assert data["total_results"] >= 5
