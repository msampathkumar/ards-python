"""FastAPI Server for ARDS Directory Service with Google-Style UI and REST API."""

import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ards.models import ResourceRegistration, ResourceType, SearchResponse
from ards.registry import registry

from ards.server.interfaces import router as interfaces_router
from ards.server.verifier import verifier
from ards.plugins.base import plugin_manager
from ards.plugins.gcp_plugins import BigQueryRegistryAuditPlugin, VertexAISearchPlugin

from ards.server.registration_ui import register_router

app = FastAPI(
    title="ARDS: Agent & Resource Directory Service",
    description="Decentralized discovery engine for A2A Agents, MCP Servers, Skills, and Plugins.",
    version="1.0.0",
)

# Register default plugins
plugin_manager.register_plugin(BigQueryRegistryAuditPlugin())
plugin_manager.register_plugin(VertexAISearchPlugin())

# Mount native A2A & MCP interfaces and human/agent registration UI
app.include_router(interfaces_router)
app.include_router(register_router)

# Seed realistic initial directory entries
def _seed_initial_data():
    seed_items = [
        ResourceRegistration(
            id="agent-tokyo-warehouse",
            type=ResourceType.AGENT,
            name="Tokyo Logistics Hub Agent",
            description="Autonomous regional inventory controller for Asia-Pacific operations. Supports A2A protocol and local MCP data warehouse queries.",
            endpoint="http://localhost:8001/a2a",
            version="1.2.0",
            tags=["warehouse", "inventory", "apac", "tokyo", "supply-chain", "logistics"],
            capabilities=["inventory_query", "stock_allocation", "customs_manifest"],
            provider="Global Logistics Corp APAC",
            location="Tokyo, Japan",
            schema_url="http://localhost:8001/.well-known/agent.json",
            metadata={"currency": "JPY", "timezone": "Asia/Tokyo", "region": "APAC"},
        ),
        ResourceRegistration(
            id="agent-london-warehouse",
            type=ResourceType.AGENT,
            name="London Heathrow Distribution Hub Agent",
            description="Autonomous inventory gateway for EMEA territories. Manages cross-docking, bonded storage, and automated reorder triggers.",
            endpoint="http://localhost:8002/a2a",
            version="1.1.4",
            tags=["warehouse", "inventory", "emea", "london", "uk", "logistics"],
            capabilities=["inventory_query", "reorder_trigger", "bonded_audit"],
            provider="Global Logistics Corp EMEA",
            location="London, United Kingdom",
            schema_url="http://localhost:8002/.well-known/agent.json",
            metadata={"currency": "GBP", "timezone": "Europe/London", "region": "EMEA"},
        ),
        ResourceRegistration(
            id="agent-newyork-warehouse",
            type=ResourceType.AGENT,
            name="New York JFK Gateway Hub Agent",
            description="Americas East primary fulfillment node. Synchronizes cold storage, high-velocity electronics, and ground freight manifests.",
            endpoint="http://localhost:8003/a2a",
            version="2.0.1",
            tags=["warehouse", "inventory", "americas", "new-york", "usa", "logistics"],
            capabilities=["inventory_query", "express_shipping", "carrier_dispatch"],
            provider="Global Logistics Corp Americas",
            location="New York, USA",
            schema_url="http://localhost:8003/.well-known/agent.json",
            metadata={"currency": "USD", "timezone": "America/New_York", "region": "Americas"},
        ),
        ResourceRegistration(
            id="agent-warsaw-warehouse",
            type=ResourceType.AGENT,
            name="Warsaw Central Distribution Node Agent",
            description="Central & Eastern Europe intermodal freight hub. Connects rail corridors and pan-European distribution networks.",
            endpoint="http://localhost:8004/a2a",
            version="1.0.8",
            tags=["warehouse", "inventory", "europe", "warsaw", "poland", "logistics"],
            capabilities=["inventory_query", "intermodal_routing", "pallet_tracking"],
            provider="Global Logistics Corp CEE",
            location="Warsaw, Poland",
            schema_url="http://localhost:8004/.well-known/agent.json",
            metadata={"currency": "EUR", "timezone": "Europe/Warsaw", "region": "CEE"},
        ),
        ResourceRegistration(
            id="agent-delhi-warehouse",
            type=ResourceType.AGENT,
            name="Delhi NCR Cargo Hub Agent",
            description="South Asia high-volume manufacturing and fulfillment node. Manages high-throughput inventory and local distribution.",
            endpoint="http://localhost:8005/a2a",
            version="1.3.0",
            tags=["warehouse", "inventory", "south-asia", "delhi", "india", "logistics"],
            capabilities=["inventory_query", "bulk_dispatch", "gst_audit"],
            provider="Global Logistics Corp South Asia",
            location="Delhi, India",
            schema_url="http://localhost:8005/.well-known/agent.json",
            metadata={"currency": "INR", "timezone": "Asia/Kolkata", "region": "South Asia"},
        ),
        ResourceRegistration(
            id="mcp-sqlite-warehouse-tokyo",
            type=ResourceType.MCP,
            name="Tokyo Warehouse Read-Only MCP Server",
            description="Direct database driver exposing 6 warehouse tables (inventory, products, aisles, stock_movements) over Model Context Protocol.",
            endpoint="http://localhost:8001/mcp",
            version="0.9.5",
            tags=["mcp", "database", "sqlite", "read-only", "tokyo"],
            capabilities=["schema_discovery", "execute_readonly_sql", "stock_lookup"],
            provider="Logistics Data Platform",
            location="Tokyo, Japan",
            schema_url="http://localhost:8001/mcp/schema",
        ),
        ResourceRegistration(
            id="skill-inventory-audit",
            type=ResourceType.SKILL,
            name="Global Inventory Audit & Reconciliation Skill",
            description="Reusable multi-agent procedure for federated variance reconciliation across asynchronous warehouse nodes.",
            endpoint="https://github.com/ards-project/skills/inventory-audit",
            version="1.0.0",
            tags=["skill", "audit", "reconciliation", "finance"],
            capabilities=["variance_detection", "executive_reporting"],
        ),
    ]
    for item in seed_items:
        registry.register(item)

_seed_initial_data()


# HTML Google Search Template (Tailwind CDN, responsive, lightweight)
GOOGLE_SEARCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ARDS - Agent & Resource Directory Service</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif; }
    .google-logo { font-family: 'Google Sans', sans-serif; }
  </style>
</head>
<body class="bg-white text-gray-800 flex flex-col min-h-screen">

  <!-- Top Navigation Bar -->
  <header class="flex justify-between items-center px-6 py-4 border-b border-gray-100">
    <div class="flex items-center space-x-4">
      <span class="text-xs font-semibold uppercase tracking-wider text-blue-600 bg-blue-50 px-2.5 py-1 rounded-full border border-blue-200">A2A Specification Ready</span>
      <span class="text-xs text-gray-500 hidden sm:inline">RFC-Draft Agent2Agent Directory Service</span>
    </div>
    <div class="flex items-center space-x-4 text-sm font-medium">
      <a href="/register" class="text-blue-600 hover:text-blue-700 font-semibold bg-blue-50 px-3 py-1 rounded-md border border-blue-100">+ Register Resource</a>
      <a href="/api/v1/resources" class="text-gray-600 hover:text-blue-600">REST API</a>
      <a href="/docs" class="text-gray-600 hover:text-blue-600">Swagger</a>
      <a href="https://github.com/msampathkumar/ards-python" target="_blank" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-md shadow-sm transition">GitHub Repo</a>
    </div>
  </header>

  <!-- Search / Results Main Container -->
  <main class="flex-grow flex flex-col items-center justify-start px-4 pt-12 pb-16 max-w-4xl mx-auto w-full">
    
    <!-- ARDS Logo -->
    <div class="text-center mb-8">
      <h1 class="google-logo text-6xl font-bold tracking-tight mb-2">
        <span class="text-blue-600">A</span><span class="text-red-500">R</span><span class="text-yellow-500">D</span><span class="text-green-500">S</span>
      </h1>
      <p class="text-gray-500 text-sm font-medium">Agent & Resource Directory Service for Autonomous Meshes</p>
    </div>

    <!-- Search Box -->
    <form action="/" method="GET" class="w-full max-w-2xl mb-8">
      <div class="relative flex items-center shadow-md hover:shadow-lg focus-within:shadow-lg rounded-full border border-gray-200 hover:border-gray-300 transition px-5 py-3.5 bg-white">
        <svg class="w-5 h-5 text-gray-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
        </svg>
        <input 
          type="text" 
          name="q" 
          value="{{ query }}" 
          placeholder="Search for agents, MCP databases, skills, warehouse locations (e.g., Tokyo, inventory)..." 
          class="w-full focus:outline-none text-base text-gray-800 placeholder-gray-400"
          autofocus
        />
        {% if query %}
        <a href="/" class="text-gray-400 hover:text-gray-600 text-sm font-bold mr-3">✕</a>
        {% endif %}
      </div>

      <!-- Filter Chips -->
      <div class="flex flex-wrap items-center justify-center gap-2 mt-4">
        <a href="/?q={{ query }}" class="px-3.5 py-1 rounded-full text-xs font-medium border {% if not type_filter %}bg-gray-900 text-white border-gray-900{% else %}bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100{% endif %}">All Types</a>
        <a href="/?q={{ query }}&type=agent" class="px-3.5 py-1 rounded-full text-xs font-medium border {% if type_filter == 'agent' %}bg-blue-600 text-white border-blue-600{% else %}bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100{% endif %}">🤖 Agents</a>
        <a href="/?q={{ query }}&type=mcp" class="px-3.5 py-1 rounded-full text-xs font-medium border {% if type_filter == 'mcp' %}bg-purple-600 text-white border-purple-600{% else %}bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100{% endif %}">🔌 MCP Servers</a>
        <a href="/?q={{ query }}&type=skill" class="px-3.5 py-1 rounded-full text-xs font-medium border {% if type_filter == 'skill' %}bg-emerald-600 text-white border-emerald-600{% else %}bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100{% endif %}">⚡ Skills</a>
      </div>
    </form>

    <!-- Stats Bar -->
    <div class="w-full flex justify-between items-center text-xs text-gray-500 mb-6 border-b border-gray-100 pb-3">
      <span>About {{ total_results }} results ({{ execution_time_ms }} ms)</span>
      <span>Registry Status: <span class="text-green-600 font-semibold">● 100% Operational</span></span>
    </div>

    <!-- Search Results List -->
    <div class="w-full space-y-6">
      {% for item in results %}
      <div class="bg-white p-5 rounded-xl border border-gray-100 hover:border-gray-200 hover:shadow-sm transition">
        <div class="flex items-start justify-between">
          <div class="flex items-center space-x-2 mb-1">
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full
              {% if item.type == 'agent' %}bg-blue-100 text-blue-800
              {% elif item.type == 'mcp' %}bg-purple-100 text-purple-800
              {% elif item.type == 'skill' %}bg-green-100 text-green-800
              {% else %}bg-gray-100 text-gray-800{% endif %}">
              {{ item.type.upper() }}
            </span>
            {% if item.location %}
            <span class="text-xs text-gray-500 flex items-center">
              📍 {{ item.location }}
            </span>
            {% endif %}
            <span class="text-xs text-gray-400">• v{{ item.version }}</span>
          </div>
          <span class="text-xs font-mono text-gray-400">{{ item.id }}</span>
        </div>

        <h3 class="text-lg font-medium text-blue-700 hover:underline cursor-pointer">
          <a href="{{ item.endpoint }}" target="_blank">{{ item.name }}</a>
        </h3>

        <p class="text-xs font-mono text-emerald-700 truncate mb-2">{{ item.endpoint }}</p>
        
        <p class="text-sm text-gray-600 mb-3 leading-relaxed">{{ item.description }}</p>

        <!-- Capabilities & Tags -->
        <div class="flex flex-wrap gap-1.5 items-center">
          {% for cap in item.capabilities %}
          <span class="text-xs bg-gray-100 text-gray-700 px-2 py-0.5 rounded font-mono">⚡ {{ cap }}</span>
          {% endfor %}
          {% for tag in item.tags %}
          <span class="text-xs bg-slate-50 text-slate-500 px-2 py-0.5 rounded border border-slate-100">#{{ tag }}</span>
          {% endfor %}
        </div>
      </div>
      {% else %}
      <div class="text-center py-16 text-gray-500">
        <p class="text-lg font-medium mb-1">No resources found matching your query.</p>
        <p class="text-sm">Try searching for "Tokyo", "London", "inventory", or "mcp".</p>
      </div>
      {% endfor %}
    </div>

  </main>

  <!-- Footer -->
  <footer class="bg-gray-50 border-t border-gray-200 py-6 px-6 text-xs text-gray-500 flex flex-col sm:flex-row justify-between items-center gap-4">
    <div>ARDS Engine • Decentralized Discovery Protocol for Agent2Agent Meshes</div>
    <div class="flex space-x-6">
      <a href="/api/v1/resources" class="hover:underline">Catalog JSON</a>
      <a href="https://github.com/msampathkumar/ards-python" class="hover:underline">GitHub</a>
      <a href="/docs" class="hover:underline">API Reference</a>
    </div>
  </footer>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, q: str = "", type: Optional[str] = None):
    """Google-search styled discovery home page."""
    type_filter = None
    if type and type.lower() in ("agent", "skill", "plugin", "mcp"):
        type_filter = ResourceType(type.lower())

    resp = registry.search(query=q, type_filter=type_filter)

    # Simple server-side rendering
    rendered = GOOGLE_SEARCH_HTML.replace("{{ query }}", q or "")
    rendered = rendered.replace("{{ total_results }}", str(resp.total_results))
    rendered = rendered.replace("{{ execution_time_ms }}", str(resp.execution_time_ms))
    
    # Handle conditional type filters in template
    rendered = rendered.replace("{{ type_filter }}", type or "")
    rendered = rendered.replace("{% if not type_filter %}bg-gray-900 text-white border-gray-900{% else %}bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100{% endif %}",
                                "bg-gray-900 text-white border-gray-900" if not type else "bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100")
    for t in ("agent", "mcp", "skill"):
        active_class = "bg-blue-600 text-white border-blue-600" if t == "agent" else ("bg-purple-600 text-white border-purple-600" if t == "mcp" else "bg-emerald-600 text-white border-emerald-600")
        inactive_class = "bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100"
        tag_str = f"{{% if type_filter == '{t}' %}}{active_class}{{% else %}}{inactive_class}{{% endif %}}"
        rendered = rendered.replace(tag_str, active_class if type == t else inactive_class)

    # Render results items dynamically
    items_html = ""
    for item in resp.results:
        type_badge = "bg-blue-100 text-blue-800" if item.type == ResourceType.AGENT else ("bg-purple-100 text-purple-800" if item.type == ResourceType.MCP else "bg-green-100 text-green-800")
        caps_html = "".join([f'<span class="text-xs bg-gray-100 text-gray-700 px-2 py-0.5 rounded font-mono">⚡ {c}</span>' for c in item.capabilities])
        tags_html = "".join([f'<span class="text-xs bg-slate-50 text-slate-500 px-2 py-0.5 rounded border border-slate-100">#{tg}</span>' for tg in item.tags])
        loc_html = f'<span class="text-xs text-gray-500 flex items-center">📍 {item.location}</span>' if item.location else ""

        items_html += f"""
        <div class="bg-white p-5 rounded-xl border border-gray-100 hover:border-gray-200 hover:shadow-sm transition">
          <div class="flex items-start justify-between">
            <div class="flex items-center space-x-2 mb-1">
              <span class="text-xs font-semibold px-2 py-0.5 rounded-full {type_badge}">
                {item.type.value.upper()}
              </span>
              {loc_html}
              <span class="text-xs text-gray-400">• v{item.version}</span>
            </div>
            <span class="text-xs font-mono text-gray-400">{item.id}</span>
          </div>

          <h3 class="text-lg font-medium text-blue-700 hover:underline cursor-pointer">
            <a href="{item.endpoint}" target="_blank">{item.name}</a>
          </h3>

          <p class="text-xs font-mono text-emerald-700 truncate mb-2">{item.endpoint}</p>
          <p class="text-sm text-gray-600 mb-3 leading-relaxed">{item.description}</p>

          <div class="flex flex-wrap gap-1.5 items-center">
            {caps_html}
            {tags_html}
          </div>
        </div>
        """

    if not resp.results:
        items_html = """
        <div class="text-center py-16 text-gray-500">
          <p class="text-lg font-medium mb-1">No resources found matching your query.</p>
          <p class="text-sm">Try searching for "Tokyo", "London", "inventory", or "mcp".</p>
        </div>
        """

    # Replace jinja loop block
    start_loop = rendered.find("{% for item in results %}")
    end_loop = rendered.find("{% endfor %}") + len("{% endfor %}")
    if start_loop != -1 and end_loop != -1:
        rendered = rendered[:start_loop] + items_html + rendered[end_loop:]

    return HTMLResponse(rendered)


# REST API Endpoints
@app.get("/api/v1/search", response_model=SearchResponse)
async def api_search(q: str = "", type: Optional[str] = None):
    type_filter = None
    if type and type.lower() in ("agent", "skill", "plugin", "mcp"):
        type_filter = ResourceType(type.lower())
    return registry.search(query=q, type_filter=type_filter)


@app.get("/api/v1/resources")
async def api_list_resources(type: Optional[str] = None):
    type_filter = None
    if type and type.lower() in ("agent", "skill", "plugin", "mcp"):
        type_filter = ResourceType(type.lower())
    return registry.list_all(type_filter=type_filter)


@app.post("/api/v1/resources", response_model=ResourceRegistration)
async def api_register_resource(res: ResourceRegistration):
    # Verify endpoint and schema security
    verified, msg = await verifier.verify(res)
    if not verified:
        raise HTTPException(status_code=400, detail=msg)

    registered = registry.register(res)
    # Trigger post-registration hooks (e.g., BigQuery audit stream)
    await plugin_manager.trigger_post_registration(registered)
    return registered


@app.get("/api/v1/resources/{res_id}", response_model=ResourceRegistration)
async def api_get_resource(res_id: str):
    res = registry.get(res_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    return res
