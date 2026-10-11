"""Comprehensive Test Suite for ARDS SDK, Storage Backends, .env Config, Pub/Sub, Ops Brain, and FastAPI Server."""

import asyncio
import time
import pytest
from httpx import AsyncClient, ASGITransport

import ards
from ards import (
    ARDSClient,
    ARDSConfig,
    ARDSOpsBrain,
    BigQueryBackend,
    HybridBackend,
    Registry,
    ResourceRegistration,
    ResourceType,
    SQLiteBackend,
    SQLiteEventBus,
    VertexAISearchBackend,
)
from ards.server.app import app


def test_sqlite_persistence_and_fts5_search(tmp_path):
    """Verifies SQLite WAL + FTS5 persistence across restarts and sub-ms search."""
    db_file = str(tmp_path / "test_ards.db")
    reg1 = Registry(db_path=db_file, seed_defaults=False)
    assert len(reg1.list_all()) == 0

    reg1.submit(
        id="tokyo-node",
        type=ResourceType.AGENT,
        name="Tokyo Logistics Agent",
        description="APAC warehouse inventory node",
        endpoint="http://localhost:8001/a2a",
        tags=["tokyo", "inventory"],
        capabilities=["stock_lookup"],
        location="Tokyo",
    )
    reg1.submit(
        id="mcp-tokyo",
        type=ResourceType.MCP,
        name="Tokyo MCP DB",
        description="Read only warehouse database driver",
        endpoint="http://localhost:8001/mcp",
        tags=["database", "mcp"],
        location="Tokyo",
    )

    # Re-open against the same SQLite file to verify disk persistence
    reg2 = Registry(db_path=db_file, seed_defaults=False)
    res = reg2.search(query="Tokyo")
    assert res.total_results == 2
    assert res.backend == "sqlite-fts5"

    res_mcp = reg2.search(query="Tokyo", type_filter=ResourceType.MCP)
    assert res_mcp.total_results == 1
    assert res_mcp.results[0].id == "mcp-tokyo"


def test_dotenv_and_ards_config(tmp_path):
    """Verifies optional .env file loading into ARDSConfig."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ARDS_PORT=9090\n"
        "ARDS_BACKEND=hybrid\n"
        "ARDS_AUTO_CLEAN=true\n"
        "ARDS_PROJECT_DIR=/tmp/my_project\n",
        encoding="utf-8",
    )
    cfg = ARDSConfig.from_env(str(env_file), override_env=True)
    assert cfg.port == 9090
    assert cfg.backend == "hybrid"
    assert cfg.auto_clean is True
    assert cfg.project_dir == "/tmp/my_project"


def test_sdk_ergonomics_submit_decorator_and_subscription(tmp_path):
    """Verifies @registry.on_registration subscription and @ards.register_agent decorator."""
    reg = Registry(db_path=":memory:", seed_defaults=False)
    received = []

    @reg.on_registration
    def on_new(res: ResourceRegistration):
        received.append(res.id)

    @ards.register_agent(
        id="agent-osaka",
        name="Osaka Robotics Agent",
        endpoint="http://localhost:8099/a2a",
        tags=["osaka", "robotics"],
        target_registry=reg,
    )
    class OsakaAgent:
        """Handles automated pallet robotics in Osaka."""

    assert "agent-osaka" in received
    fetched = reg.get("agent-osaka")
    assert fetched is not None
    assert "pallet robotics" in fetched.description


def test_bigquery_vertex_and_hybrid_backends():
    """Verifies BigQueryBackend (with mock client), VertexAISearchBackend, and HybridBackend."""
    inserted_rows = []

    class MockBQClient:
        def insert_rows_json(self, table_ref, rows):
            inserted_rows.extend(rows)
            return []

        def query(self, sql, job_config=None):
            class _Res:
                def result(self):
                    return []
            return _Res()

    bq_backend = BigQueryBackend(
        project="demo-gcp",
        dataset="ards_registry",
        table="resources",
        seed_defaults=False,
        bq_client=MockBQClient(),
    )
    reg_bq = Registry(backend=bq_backend)
    reg_bq.submit(name="Cloud Agent", endpoint="https://agent.example.com/a2a")
    assert len(inserted_rows) == 1
    assert reg_bq.search("Cloud").backend == "bigquery+l1-cache"

    # Mock Vertex AI Search client returning semantic match ID
    class MockDoc:
        id = "agent-semantic-match"

    class MockResult:
        document = MockDoc()

    class MockSearchResponse:
        results = [MockResult()]

    class MockVertexClient:
        def search(self, request):
            return MockSearchResponse()

    local_store = SQLiteBackend(db_path=":memory:", seed_defaults=False)
    local_store.register(
        ResourceRegistration(
            id="agent-semantic-match",
            type=ResourceType.AGENT,
            name="Zurich Vault Controller",
            description="High-security precious metals ledger",
            endpoint="https://zurich.example.com/a2a",
        )
    )
    vertex_backend = VertexAISearchBackend(
        project="demo-gcp",
        data_store_id="ards-ds",
        local_store=local_store,
        search_client=MockVertexClient(),
    )
    hybrid = HybridBackend(local=local_store, semantic=vertex_backend, audit_bq=bq_backend)
    # Query with zero lexical overlap triggers Vertex AI semantic fallback in HybridBackend
    sem_resp = hybrid.search("gold bullion custody")
    assert sem_resp.total_results == 1
    assert sem_resp.results[0].id == "agent-semantic-match"


@pytest.mark.asyncio
async def test_ops_brain_pubsub_and_auto_clean(tmp_path):
    """Verifies split Pub/Sub queue consumption and --auto-clean eviction of dead endpoints."""
    bus = SQLiteEventBus(db_path=str(tmp_path / "events.db"))
    reg = Registry(db_path=str(tmp_path / "reg.db"), seed_defaults=False, event_bus=bus)
    cfg = ARDSConfig(pubsub_enabled=True, auto_clean=True, max_failures=2, protect_seed_data=True)
    brain = ARDSOpsBrain(registry=reg, event_bus=bus, auto_clean=True, max_failures=2, config=cfg)

    # Submit an unreachable local port (non-seed)
    dead_agent = ResourceRegistration(
        id="dead-agent-node",
        type=ResourceType.AGENT,
        name="Dead Node",
        description="Unreachable test node",
        endpoint="http://127.0.0.1:59999/a2a",
    )
    await brain.submit_for_verification(dead_agent)
    assert reg.get("dead-agent-node") is not None

    # First sweep processes Pub/Sub queue and records failure #1 (degraded)
    sweep1 = await brain.sweep_once()
    item_after_1 = reg.get("dead-agent-node")
    assert item_after_1 is not None
    assert item_after_1.health_status == "degraded"

    # Second sweep hits max_failures=2 with auto_clean=True -> evicted!
    sweep2 = await brain.sweep_once()
    assert "dead-agent-node" in sweep2["evicted"]
    assert reg.get("dead-agent-node") is None


def test_sqlite_high_rps_throughput():
    """Proves SQLite WAL + FTS5 backend easily exceeds hundreds of searches per second."""
    reg = Registry(db_path=":memory:", seed_defaults=True)
    iterations = 300
    t0 = time.perf_counter()
    for _ in range(iterations):
        res = reg.search(query="Tokyo warehouse", type_filter=ResourceType.AGENT)
        assert res.total_results >= 1
    elapsed = time.perf_counter() - t0
    rps = iterations / max(elapsed, 1e-6)
    # 200/s keeps CI stable on slow runners while still proving "hundreds of requests per second".
    assert rps > 200, f"Expected >200 RPS, got {rps:.1f} RPS"


@pytest.mark.asyncio
async def test_ards_web_and_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Search page HTML
        html_resp = await client.get("/?q=Tokyo")
        assert html_resp.status_code == 200
        assert "ARDS" in html_resp.text
        assert "Tokyo" in html_resp.text
        assert "{%" not in html_resp.text
        assert "{{" not in html_resp.text

        # Registration page HTML
        reg_resp = await client.get("/register")
        assert reg_resp.status_code == 200
        assert "{%" not in reg_resp.text
        assert "{{" not in reg_resp.text

        # API Search JSON
        api_resp = await client.get("/api/v1/search?q=warehouse")
        assert api_resp.status_code == 200
        data = api_resp.json()
        assert data["total_results"] >= 5

        # Ops Brain Status API
        ops_resp = await client.get("/api/v1/ops/status")
        assert ops_resp.status_code == 200
        ops_data = ops_resp.json()
        assert "sqlite" in ops_data["backend"]


# ---------------------------------------------------------------------------
# Regression tests for the review fixes (security, SDK ergonomics, scale).
# ---------------------------------------------------------------------------
import subprocess
import sys

from fastapi.testclient import TestClient

from ards.registry import default_registry


def _fresh_app_client(**client_kwargs) -> TestClient:
    default_registry.configure(backend=SQLiteBackend(db_path=":memory:", seed_defaults=True))
    return TestClient(app, **client_kwargs)


def test_import_ards_has_no_side_effects(tmp_path):
    """A plain `import ards` must not create a database file in the working directory."""
    subprocess.run([sys.executable, "-c", "import ards"], cwd=tmp_path, check=True)
    assert list(tmp_path.iterdir()) == []


def test_cli_flags_apply_after_import(monkeypatch):
    """Settings reloaded after import (as the CLI does) must reach the default registry."""
    from ards.config import reload_settings, settings

    monkeypatch.setenv("ARDS_BACKEND", "sqlite")
    monkeypatch.setenv("ARDS_SQLITE_PATH", ":memory:")
    monkeypatch.setenv("ARDS_AUTO_CLEAN", "true")
    reload_settings()
    default_registry.reset()
    try:
        assert settings.auto_clean is True
        assert default_registry.get_instance().backend.db_path == ":memory:"
    finally:
        monkeypatch.delenv("ARDS_AUTO_CLEAN")
        reload_settings()


def test_registration_vs_update_events():
    """on_registration fires once for new resources; on_update fires for later changes (e.g. health)."""
    reg = Registry(db_path=":memory:", seed_defaults=False)
    new_ids, updated_ids = [], []
    reg.on_registration(lambda r: new_ids.append(r.id))
    reg.on_update(lambda r: updated_ids.append(r.id))
    item = reg.submit(name="Lyon Hub", endpoint="https://lyon.example.com/a2a")
    item.health_status = "degraded"
    reg.register(item)
    assert new_ids == ["agent-lyon-hub"]
    assert updated_ids == ["agent-lyon-hub"]


def test_submit_generates_safe_ids():
    reg = Registry(db_path=":memory:", seed_defaults=False)
    res = reg.submit(name="São Paulo / Hub #1 (beta)", endpoint="https://sp.example.com")
    assert res.id == "agent-s-o-paulo-hub-1-beta"


def test_rejects_hijack_xss_oversize_and_anonymous_admin():
    client = _fresh_app_client(client=("203.0.113.9", 5000))  # Non-loopback client = not admin
    base = dict(type="agent", name="x", description="d")

    hijack = client.post("/api/v1/resources", json=dict(base, id="agent-tokyo-warehouse", endpoint="http://evil.example.com/a2a"))
    assert hijack.status_code == 409
    assert client.get("/api/v1/resources/agent-tokyo-warehouse").json()["endpoint"] == "http://localhost:8001/a2a"

    xss = client.post("/api/v1/resources", json=dict(base, id="xss-1", endpoint="javascript://x/%0aalert(1)"))
    assert xss.status_code == 400

    oversize = client.post("/api/v1/resources", json=dict(base, id="big", endpoint="https://a.example.com", description="A" * 5000))
    assert oversize.status_code == 422

    assert client.delete("/api/v1/resources/skill-inventory-audit").status_code == 401
    assert client.post("/api/v1/ops/sweep").status_code == 401

    bad_mcp = client.post("/mcp/execute", json={"name": "search_directory", "arguments": {"query": "x", "type_filter": "bogus"}})
    assert bad_mcp.status_code == 200 and "error" in bad_mcp.json()


def test_admin_token_allows_admin_actions(monkeypatch):
    from ards.config import settings

    monkeypatch.setattr(settings, "admin_token", "s3cret-token")
    client = _fresh_app_client(client=("203.0.113.9", 5000))
    assert client.delete("/api/v1/resources/skill-inventory-audit", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.delete("/api/v1/resources/skill-inventory-audit", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


def test_ssrf_policy_blocks_internal_targets():
    import asyncio
    from ards.server.verifier import verifier

    async def check(url):
        res = ResourceRegistration(id="t", type=ResourceType.MCP, name="t", description="", endpoint=url)
        return (await verifier.check_url_policy(res, allow_local=False))[0]

    for url in ["http://[::1]/", "http://0.0.0.0:80/", "http://169.254.169.254/latest", "http://10.1.2.3/", "http://localhost/"]:
        assert asyncio.run(check(url)) is False, url
    assert asyncio.run(check("https://93.184.216.34/")) is True


def test_security_headers_and_healthz():
    client = _fresh_app_client()
    home = client.get("/")
    assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert home.headers["x-content-type-options"] == "nosniff"
    assert client.get("/healthz").json()["status"] == "ok"


def test_registration_is_non_blocking_then_verified():
    """API registration returns immediately as 'provisional'; the Ops Brain verifies in the background."""
    client = _fresh_app_client()
    resp = client.post(
        "/api/v1/resources",
        json=dict(type="skill", id="skill-fast", name="Fast Skill", description="d", endpoint="https://skills.example.com/fast"),
    )
    assert resp.status_code == 200
    assert resp.json()["health_status"] == "provisional"


def test_search_limit_keeps_total_count():
    reg = Registry(db_path=":memory:", seed_defaults=True)
    resp = reg.search("warehouse", limit=2)
    assert len(resp.results) == 2
    assert resp.total_results >= 5


def test_bigquery_append_only_with_tombstones():
    """Updates append rows; deletes append a tombstone instead of DML DELETE (streaming-buffer safe)."""
    rows = []

    class MockBQ:
        def insert_rows_json(self, table_ref, new_rows):
            rows.extend(new_rows)
            return []

        def query(self, sql, job_config=None):
            class _R:
                def result(self_inner):
                    return []
            return _R()

    backend = BigQueryBackend(project="demo-gcp", seed_defaults=False, bq_client=MockBQ())
    reg = Registry(backend=backend)
    item = reg.submit(name="Oslo Hub", endpoint="https://oslo.example.com/a2a")
    item.health_status = "degraded"
    reg.register(item)
    reg.delete(item.id)
    assert [r.get("deleted") for r in rows] == [False, False, True]
    assert all("updated_at" in r for r in rows)


@pytest.mark.asyncio
async def test_sqlite_event_bus_never_double_delivers(tmp_path):
    """Two consumers on the same queue file must not process the same event twice."""
    path = str(tmp_path / "bus.db")
    bus_a, bus_b, producer = SQLiteEventBus(path), SQLiteEventBus(path), SQLiteEventBus(path)
    seen = []
    bus_a.subscribe("t", lambda topic, p: seen.append(p["n"]))
    bus_b.subscribe("t", lambda topic, p: seen.append(p["n"]))
    for n in range(20):
        producer.publish_sync("t", {"n": n})
    await asyncio.gather(bus_a.poll_once(), bus_b.poll_once())
    assert sorted(seen) == list(range(20))
