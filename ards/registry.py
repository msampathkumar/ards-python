"""ARDS In-Memory Registry with Fast Multi-Field Tokenized Search."""

from typing import List, Optional, Dict, Any
import time
from ards.models import ResourceRegistration, ResourceType, SearchResponse


class Registry:
    def __init__(self):
        self._resources: Dict[str, ResourceRegistration] = {}
        self._seed_default_catalog()

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        res.created_at = time.time()
        self._resources[res.id] = res
        return res

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        return self._resources.get(res_id)

    def delete(self, res_id: str) -> bool:
        if res_id in self._resources:
            del self._resources[res_id]
            return True
        return False

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        items = list(self._resources.values())
        if type_filter:
            items = [item for item in items if item.type == type_filter]
        return items

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        start_time = time.perf_counter()
        q = query.strip().lower()

        candidates = list(self._resources.values())
        if type_filter:
            candidates = [c for c in candidates if c.type == type_filter]

        if not q:
            results = candidates
        else:
            query_tokens = [w for w in q.split() if len(w) > 1]
            scored_results = []
            for item in candidates:
                score = 0
                searchable_text = f"{item.name} {item.description} {' '.join(item.tags)} {' '.join(item.capabilities)} {item.location or ''}".lower()

                # Full phrase match
                if q in searchable_text:
                    score += 25

                # Individual word tokens match
                for token in query_tokens:
                    if token in item.name.lower():
                        score += 15
                    if token in [t.lower() for t in item.tags]:
                        score += 12
                    elif token in ' '.join(item.tags).lower():
                        score += 6
                    if item.location and token in item.location.lower():
                        score += 10
                    if token in item.description.lower():
                        score += 4
                    if any(token in cap.lower() for cap in item.capabilities):
                        score += 8

                if score > 0:
                    scored_results.append((score, item))

            scored_results.sort(key=lambda x: x[0], reverse=True)
            results = [item for _, item in scored_results]

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return SearchResponse(
            query=query,
            type_filter=type_filter.value if type_filter else None,
            total_results=len(results),
            execution_time_ms=round(elapsed_ms, 3),
            results=results,
        )

    def _seed_default_catalog(self):
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
            self.register(item)


registry = Registry()
