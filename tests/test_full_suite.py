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

import pytest
from ards.server.verifier import RegistrationVerifier

@pytest.mark.asyncio
async def test_verifier_ssrf_rejections():
    v = RegistrationVerifier()
    
    # 1. Reject localhost
    res_local = ResourceRegistration(
        id="test-local",
        name="Localhost Agent",
        type=ResourceType.AGENT,
        endpoint="http://localhost:8000/agent",
        description="Localhost testing"
    )
    ok, msg = await v.verify(res_local, allow_local=False)
    assert not ok
    assert "SECURITY_REJECTION" in msg

    # 2. Reject 127.0.0.1
    res_loopback = ResourceRegistration(
        id="test-loopback",
        name="Loopback Agent",
        type=ResourceType.AGENT,
        endpoint="http://127.0.0.1:8080/agent",
        description="Loopback testing"
    )
    ok, msg = await v.verify(res_loopback, allow_local=False)
    assert not ok
    assert "SECURITY_REJECTION" in msg

    # 3. Reject 169.254.169.254 (Cloud metadata)
    res_meta = ResourceRegistration(
        id="test-meta",
        name="Metadata Agent",
        type=ResourceType.AGENT,
        endpoint="http://169.254.169.254/latest/meta-data",
        description="Cloud metadata target"
    )
    ok, msg = await v.verify(res_meta, allow_local=False)
    assert not ok
    assert "SECURITY_REJECTION" in msg

    # 4. Opt-in with allow_local=True allows local endpoint
    ok_opt, msg_opt = await v.verify(res_local, allow_local=True)
    # It will either be accepted or probe fail (unverified), but NOT security rejected
    assert "SECURITY_REJECTION" not in msg_opt
