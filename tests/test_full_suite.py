"""Comprehensive Test Suite for ARDS SDK, Storage Backends, .env Config, Pub/Sub, Ops Brain, and FastAPI Server."""

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
    assert rps > 500, f"Expected >500 RPS, got {rps:.1f} RPS"


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
