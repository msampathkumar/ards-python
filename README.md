# ARDS Python SDK 🌐🔎

> **ARDS: Agent & Resource Directory Service (Python Core SDK & Discovery Server)**  
> Production-grade Python SDK and FastAPI server for registering, indexing, and discovering A2A Agents, MCP Servers, Skills, and Plugins with a Google-search styled user interface and asynchronous client.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![Protocol](https://img.shields.io/badge/Protocol-A2A%20%2B%20MCP-green)](https://github.com/a2a-protocol)

---

## 💡 Why ARDS?

Traditional multi-agent systems rely on fragile, hardcoded environment variables (`AGENT_B_URL=http://...`). When new agents or database instances spin up across global regions, central orchestrators must be manually reconfigured and redeployed.

**ARDS** acts as the decentralized "DNS & Google Search" layer for multi-agent meshes:
1. **Google-Search Styled Discovery UI**: A lightweight, responsive web interface allowing humans, operators, and developers to explore registered agents, MCP database drivers, and skills with millisecond search times.
2. **Standardized A2A AgentCard Resolution**: Automatically tracks and resolves `.well-known/agent.json` specifications.
3. **Multi-Field Tag & Capability Filtering**: Filter by location (`Tokyo`, `London`, `Warsaw`), type (`agent`, `mcp`, `skill`), or operational capability.
4. **Python Async SDK**: Enables orchestrator agents to dynamically discover peers at runtime without human intervention.

---

## 🚀 Quickstart

### 1. Installation
```bash
git clone https://github.com/msampathkumar/ards-python.git
cd ards-python
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Run the ARDS Server
```bash
python -m uvicorn ards.server.app:app --host 0.0.0.0 --port 8000 --reload
```
Open **`http://localhost:8000`** in your browser to interact with the Google Search discovery interface.

### 3. Dynamic Python Client Usage
```python
import asyncio
from ards.client.client import ARDSClient
from ards.models import ResourceType

async def main():
    client = ARDSClient("http://localhost:8000")
    
    # Search for active agents in Asia
    response = await client.search(query="Tokyo warehouse", type_filter=ResourceType.AGENT)
    for agent in response.results:
        print(f"Found: {agent.name} at {agent.endpoint}")

asyncio.run(main())
```

---

## 🏛️ Associated Enterprise Showcase
For complete multi-regional enterprise demonstrations and conference keynote materials combining ARDS with A2A protocol and Model Context Protocol (MCP), see:
👉 **[a2a-google-cloud-enterprise-demos](https://github.com/msampathkumar/a2a-google-cloud-enterprise-demos/tree/master/demos/09-global-warehouse-mesh-ards-mcp)**

---

## 📄 License
Licensed under the [Apache License, Version 2.0](LICENSE).
