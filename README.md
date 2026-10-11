# ARDS Python SDK 🌐🔎

> **ARDS: Agent & Resource Directory Service (Python Core SDK & Discovery Server)**  
> Production-grade Python SDK and FastAPI server for registering, indexing, and discovering A2A Agents, MCP Servers, Skills, and Plugins with a Google-search styled user interface, pluggable storage backends (`SQLite FTS5`, `BigQuery`, `Vertex AI Search`, `Hybrid`), and an autonomous **Ops Brain** (`--auto-clean`).

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![Protocol](https://img.shields.io/badge/Protocol-A2A%20%2B%20MCP-green)](https://github.com/a2a-protocol)

---

## 💡 Why ARDS?

Traditional multi-agent systems rely on fragile, hardcoded environment variables (`AGENT_B_URL=http://...`). When new agents or database instances spin up across global regions, central orchestrators must be manually reconfigured and redeployed.

**ARDS** acts as the decentralized "DNS & Google Search" layer for multi-agent meshes:
1. **Google-Search Styled Discovery UI**: A lightweight, responsive web interface allowing humans, operators, and developers to explore registered agents, MCP database drivers, and skills with sub-millisecond search times.
2. **Pluggable Storage & Search Engines**:
   - **Default (`SQLiteBackend`)**: 100% local, zero-config SQLite with `WAL`, `mmap`, and **FTS5 BM25** full-text ranking (`<1ms` latency, `1,000+ RPS`).
   - **Online Hosted (`BigQueryBackend`)**: Cloud-backed catalog with a high-speed L1 TTL read-through cache (`100s+ RPS`).
   - **Semantic Search (`VertexAISearchBackend` & `HybridBackend`)**: Natural-language vector discovery via Google Cloud Vertex AI Search + local FTS5.
3. **Two-Plane Architecture (Serving Plane + "Brain of Ops")**:
   - Runs in a **single process by default** for zero-config simplicity.
   - Optionally decouples via **Pub/Sub** (`SQLiteEventBus` or `GCPPubSubEventBus`) so a standalone **Ops Brain Worker** (`--auto-clean`) handles continuous endpoint verification and automatic eviction of dead nodes.

---

## 🚀 Quickstart

### 1. Installation
```bash
git clone https://github.com/msampathkumar/ards-python.git
cd ards-python
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Optional: Install Google Cloud extras (BigQuery, Vertex AI Search, Pub/Sub)
pip install -e ".[gcp]"
```

### 2. Optional `.env` Configuration
Copy `.env.example` to `.env` to customize ports, project directory, SQLite path, or cloud backends (all optional — ARDS runs out of the box without a `.env` file):
```bash
cp .env.example .env
```

### 3. Run the ARDS Server
```bash
# Default single-process mode (SQLite WAL+FTS5 + embedded Ops Brain)
python -m ards.cli serve --port 8000 --reload

# Enable automatic eviction of dead/unreachable endpoints:
python -m ards.cli serve --port 8000 --auto-clean

# Scale-out mode: run a standalone Ops Brain worker with --auto-clean:
python -m ards.cli ops-worker --auto-clean --interval 30
```
Open **`http://localhost:8000`** in your browser to interact with the Google Search discovery interface.

---

## 🛠️ Python SDK Usage

### 1. 1-Line Registration & Decorator API
```python
import asyncio
import ards

# Decorator registration for Agent classes
@ards.register_agent(
    name="Osaka Fulfillment Agent",
    endpoint="http://localhost:8009/a2a",
    capabilities=["inventory_query", "robotics_dispatch"],
    tags=["warehouse", "apac", "osaka"],
    location="Osaka, Japan",
)
class OsakaAgent:
    """Autonomous warehouse controller for Osaka."""

# Subscribe to new registrations (fires once per new resource)
@ards.on_registration
async def on_new_resource(res: ards.ResourceRegistration):
    print(f"[Subscribed] Registered {res.name} ({res.id}) -> {res.health_status}")

# Subscribe to changes of existing resources (e.g. health status set by the Ops Brain)
@ards.on_update
async def on_changed(res: ards.ResourceRegistration):
    print(f"[Update] {res.id} is now {res.health_status}")

async def main():
    # 1-line submission for humans or agents
    await ards.submit(
        name="Kyoto Analytics MCP",
        endpoint="http://localhost:8010/mcp",
        type="mcp",
        capabilities=["sql_query"],
        location="Kyoto, Japan",
    )

asyncio.run(main())
```

### 2. Pluggable Storage Backends (`sqlite` | `bigquery` | `vertex` | `hybrid`)
```python
from ards import Registry, SQLiteBackend, BigQueryBackend, VertexAISearchBackend, HybridBackend

# 100% Local SQLite WAL + FTS5 BM25 (Default)
local_reg = Registry(backend=SQLiteBackend("ards_registry.db"))

# Online Cloud Hosted (BigQuery + L1 Read-Through Cache)
bq_reg = Registry(backend=BigQueryBackend(project="my-gcp-project", dataset="ards_registry"))

# Tiered Enterprise Hybrid (SQLite FTS5 + Vertex AI Semantic Search + BigQuery Sync)
hybrid_reg = Registry(backend=HybridBackend())
```

### 3. High-RPS Async Client SDK
```python
import asyncio
from ards import ARDSClient, ResourceType

async def main():
    async with ARDSClient("http://localhost:8000", cache_ttl=5.0) as client:
        response = await client.search(query="Tokyo warehouse", type_filter=ResourceType.AGENT)
        for agent in response.results:
            print(f"Found: {agent.name} at {agent.endpoint}")

asyncio.run(main())
```

---

## 🔐 Security & Production

Safe defaults work locally with zero setup. Before hosting ARDS publicly:

| Setting | Why |
| :--- | :--- |
| `ARDS_ADMIN_TOKEN=<long random value>` | Admin actions (`DELETE`, `/api/v1/ops/sweep`, changing an existing id's endpoint) need `Authorization: Bearer <token>`. Without a token, they are allowed only from the same machine. |
| `ARDS_ALLOW_LOCAL_ENDPOINTS=false` | Blocks registering `localhost`, private IPs, and cloud metadata addresses (SSRF protection, including IPv6 and DNS names that resolve to private IPs). |
| `ARDS_HOST=0.0.0.0` only behind a proxy/load balancer | The CLI warns if you expose ARDS without an admin token. |

Built-in protections: only `http(s)` endpoints are accepted (blocks `javascript:` links), field size limits, endpoint-takeover protection (`409` when someone re-registers an existing id with a different endpoint), security headers + CSP on HTML pages, and a `/healthz` probe for Cloud Run / Kubernetes.

> [!NOTE]
> With `uvicorn --workers N`, each worker runs its own Ops Brain. For multi-worker or multi-instance setups, run the server with `--mode frontend` and a single `ards ops-worker --auto-clean`.

---

## 🏛️ Associated Enterprise Showcase
For complete multi-regional enterprise demonstrations and conference keynote materials combining ARDS with A2A protocol and Model Context Protocol (MCP), see:
👉 **[a2a-google-cloud-enterprise-demos](https://github.com/msampathkumar/a2a-google-cloud-enterprise-demos/tree/master/demos/09-global-warehouse-mesh-ards-mcp)**

---

## 📄 License
Licensed under the [Apache License, Version 2.0](LICENSE).
