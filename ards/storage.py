"""Pluggable High-Throughput Storage & Search Backends for ARDS SDK.

Supports:
1. SQLiteBackend (Default): 100% local, WAL + mmap + FTS5 BM25 full-text search (<1ms, 1000+ RPS).
2. BigQueryBackend: Online cloud-hosted storage with L1 TTL read-through cache and parameterized SQL.
3. VertexAISearchBackend: Semantic natural-language search via Google Cloud Discovery Engine + TTL cache.
4. HybridBackend: Tiered architecture combining SQLite FTS5 primary + Vertex AI semantic fallback + async BigQuery sync.
"""

from abc import ABC, abstractmethod
import asyncio
import json
import logging
import re
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

from ards.config import ARDSConfig, settings
from ards.models import ResourceRegistration, ResourceType, SearchResponse

logger = logging.getLogger("ards.storage")

_SAFE_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_BQ_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def default_seed_catalog() -> List[ResourceRegistration]:
    """Returns the 7 realistic seed items for initial ARDS directory bootstrapping."""
    return [
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
            metadata={"currency": "JPY", "timezone": "Asia/Tokyo", "region": "APAC", "seed": True},
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
            metadata={"currency": "GBP", "timezone": "Europe/London", "region": "EMEA", "seed": True},
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
            metadata={"currency": "USD", "timezone": "America/New_York", "region": "Americas", "seed": True},
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
            metadata={"currency": "EUR", "timezone": "Europe/Warsaw", "region": "CEE", "seed": True},
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
            metadata={"currency": "INR", "timezone": "Asia/Kolkata", "region": "South Asia", "seed": True},
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
            metadata={"seed": True},
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
            metadata={"seed": True},
        ),
    ]


class StorageBackend(ABC):
    """Abstract Storage & Search Engine Interface for ARDS SDK."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        pass

    @abstractmethod
    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        pass

    @abstractmethod
    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        pass

    @abstractmethod
    def delete(self, res_id: str) -> bool:
        pass

    @abstractmethod
    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        pass

    @abstractmethod
    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        pass

    def close(self) -> None:
        pass


class SQLiteBackend(StorageBackend):
    """
    Default 100% Local Storage & Search Backend.
    Optimized for sub-millisecond reads (1,000+ RPS) using:
    - SQLite WAL (Write-Ahead Logging) for non-blocking concurrent reads
    - Memory-Mapped I/O (mmap_size = 256MB) and 64MB page cache
    - FTS5 Full-Text Search virtual table with BM25 weighted ranking
    """

    def __init__(self, db_path: Optional[str] = None, seed_defaults: bool = True):
        self.db_path = db_path or settings.sqlite_path or "ards_registry.db"
        self._is_memory = self.db_path == ":memory:"
        self._lock = threading.RLock()
        self._local = threading.local()
        self._shared_conn: Optional[sqlite3.Connection] = None
        self._fts5_enabled = True

        if self._is_memory:
            self._shared_conn = self._create_connection()

        self._init_schema()
        if seed_defaults and self._count() == 0:
            for item in default_seed_catalog():
                self.register(item)

    @property
    def backend_name(self) -> str:
        return "sqlite-fts5" if self._fts5_enabled else "sqlite"

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        # Read-performance optimization pragmas
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
        conn.execute("PRAGMA cache_size=-64000;")    # 64MB cache
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._is_memory:
            assert self._shared_conn is not None
            return self._shared_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._create_connection()
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    version TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    provider TEXT,
                    location TEXT,
                    schema_url TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    health_status TEXT NOT NULL,
                    last_verified_at REAL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    verification_message TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_resources_health ON resources(health_status);")
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS resources_fts USING fts5(
                        id UNINDEXED,
                        name,
                        description,
                        tags,
                        capabilities,
                        location,
                        tokenize='porter unicode61'
                    );
                    """
                )
            except sqlite3.OperationalError:
                self._fts5_enabled = False
            conn.commit()

    def _count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) AS cnt FROM resources;").fetchone()
        return int(row["cnt"]) if row else 0

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ResourceRegistration:
        return ResourceRegistration(
            id=row["id"],
            type=ResourceType(row["type"]),
            name=row["name"],
            description=row["description"],
            endpoint=row["endpoint"],
            version=row["version"],
            tags=json.loads(row["tags_json"]),
            capabilities=json.loads(row["capabilities_json"]),
            provider=row["provider"],
            location=row["location"],
            schema_url=row["schema_url"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            health_status=row["health_status"],
            last_verified_at=row["last_verified_at"],
            consecutive_failures=row["consecutive_failures"],
            verification_message=row["verification_message"],
        )

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        if not res.created_at:
            res.created_at = time.time()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO resources (
                    id, type, name, description, endpoint, version,
                    tags_json, capabilities_json, provider, location,
                    schema_url, metadata_json, created_at, health_status,
                    last_verified_at, consecutive_failures, verification_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    name=excluded.name,
                    description=excluded.description,
                    endpoint=excluded.endpoint,
                    version=excluded.version,
                    tags_json=excluded.tags_json,
                    capabilities_json=excluded.capabilities_json,
                    provider=excluded.provider,
                    location=excluded.location,
                    schema_url=excluded.schema_url,
                    metadata_json=excluded.metadata_json,
                    created_at=excluded.created_at,
                    health_status=excluded.health_status,
                    last_verified_at=excluded.last_verified_at,
                    consecutive_failures=excluded.consecutive_failures,
                    verification_message=excluded.verification_message;
                """,
                (
                    res.id,
                    res.type.value,
                    res.name,
                    res.description,
                    res.endpoint,
                    res.version,
                    json.dumps(res.tags),
                    json.dumps(res.capabilities),
                    res.provider,
                    res.location,
                    res.schema_url,
                    json.dumps(res.metadata),
                    res.created_at,
                    res.health_status,
                    res.last_verified_at,
                    res.consecutive_failures,
                    res.verification_message,
                ),
            )
            if self._fts5_enabled:
                conn.execute("DELETE FROM resources_fts WHERE id = ?;", (res.id,))
                conn.execute(
                    """
                    INSERT INTO resources_fts (id, name, description, tags, capabilities, location)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        res.id,
                        res.name,
                        res.description,
                        " ".join(res.tags),
                        " ".join(res.capabilities),
                        res.location or "",
                    ),
                )
            conn.commit()
        return res

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM resources WHERE id = ?;", (res_id,)).fetchone()
        return self._row_to_model(row) if row else None

    def delete(self, res_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute("DELETE FROM resources WHERE id = ?;", (res_id,))
            if self._fts5_enabled:
                conn.execute("DELETE FROM resources_fts WHERE id = ?;", (res_id,))
            conn.commit()
            return cur.rowcount > 0

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        conn = self._get_conn()
        if type_filter:
            rows = conn.execute(
                "SELECT * FROM resources WHERE type = ? ORDER BY created_at DESC;",
                (type_filter.value,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM resources ORDER BY created_at DESC;").fetchall()
        return [self._row_to_model(r) for r in rows]

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        start_time = time.perf_counter()
        q = query.strip()
        conn = self._get_conn()

        if not q:
            results = self.list_all(type_filter=type_filter)
        else:
            tokens = [t.lower() for t in _SAFE_TOKEN_RE.findall(q) if len(t) > 1]
            results = []
            if self._fts5_enabled and tokens:
                # Build safe FTS5 prefix match expression: "token1"* OR "token2"*
                fts_expr = " OR ".join(f'"{t}"*' for t in tokens)
                if type_filter:
                    sql = """
                        SELECT r.*, bm25(resources_fts, 10.0, 4.0, 8.0, 8.0, 6.0) AS rank_score
                        FROM resources_fts
                        JOIN resources r ON r.id = resources_fts.id
                        WHERE resources_fts MATCH ? AND r.type = ?
                        ORDER BY rank_score ASC;
                    """
                    rows = conn.execute(sql, (fts_expr, type_filter.value)).fetchall()
                else:
                    sql = """
                        SELECT r.*, bm25(resources_fts, 10.0, 4.0, 8.0, 8.0, 6.0) AS rank_score
                        FROM resources_fts
                        JOIN resources r ON r.id = resources_fts.id
                        WHERE resources_fts MATCH ?
                        ORDER BY rank_score ASC;
                    """
                    rows = conn.execute(sql, (fts_expr,)).fetchall()
                results = [self._row_to_model(r) for r in rows]

            # Fallback lexical scoring if FTS5 returned nothing (e.g. substring match)
            if not results:
                results = self._fallback_lexical_search(q, type_filter)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return SearchResponse(
            query=query,
            type_filter=type_filter.value if type_filter else None,
            total_results=len(results),
            execution_time_ms=round(elapsed_ms, 3),
            results=results,
            backend=self.backend_name,
        )

    def _fallback_lexical_search(
        self, query: str, type_filter: Optional[ResourceType] = None
    ) -> List[ResourceRegistration]:
        q = query.strip().lower()
        candidates = self.list_all(type_filter=type_filter)
        query_tokens = [w for w in q.split() if len(w) > 1]
        scored: List[Tuple[int, ResourceRegistration]] = []
        for item in candidates:
            score = 0
            searchable = (
                f"{item.name} {item.description} {' '.join(item.tags)} "
                f"{' '.join(item.capabilities)} {item.location or ''}"
            ).lower()
            if q in searchable:
                score += 25
            for token in query_tokens:
                if token in item.name.lower():
                    score += 15
                if token in [t.lower() for t in item.tags]:
                    score += 12
                elif token in " ".join(item.tags).lower():
                    score += 6
                if item.location and token in item.location.lower():
                    score += 10
                if token in item.description.lower():
                    score += 4
                if any(token in cap.lower() for cap in item.capabilities):
                    score += 8
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def close(self) -> None:
        if self._shared_conn:
            self._shared_conn.close()
            self._shared_conn = None
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None


class BigQueryBackend(StorageBackend):
    """
    Online Cloud-Hosted Storage Backend using Google Cloud BigQuery.
    Includes a high-speed L1 SQLite/in-memory read-through cache (configurable TTL)
    so online deployments serve 100s+ RPS while persisting state in BigQuery.
    Gracefully falls back to local L1 cache if GCP credentials or SDK are unavailable.
    """

    def __init__(
        self,
        project: Optional[str] = None,
        dataset: Optional[str] = None,
        table: Optional[str] = None,
        cache_ttl: Optional[float] = None,
        seed_defaults: bool = True,
        bq_client: Optional[object] = None,
    ):
        self.project = project or settings.google_cloud_project
        self.dataset = dataset or settings.bq_dataset
        self.table = table or settings.bq_table
        self.cache_ttl = cache_ttl if cache_ttl is not None else settings.bq_cache_ttl_seconds

        if not _BQ_IDENTIFIER_RE.match(self.dataset) or not _BQ_IDENTIFIER_RE.match(self.table):
            raise ValueError("Invalid BigQuery dataset or table identifier.")

        # Fast L1 read-through cache (in-memory SQLite FTS5)
        self._l1_cache = SQLiteBackend(db_path=":memory:", seed_defaults=seed_defaults)
        self._last_sync_ts: float = 0.0
        self._bq_client = bq_client
        self._bq_available = False
        self._init_bigquery()

    @property
    def backend_name(self) -> str:
        return "bigquery+l1-cache" if self._bq_available else "bigquery-local-fallback"

    def _init_bigquery(self) -> None:
        if self._bq_client is not None:
            self._bq_available = True
            return
        if not self.project:
            logger.info("GOOGLE_CLOUD_PROJECT not set; BigQueryBackend operating in L1 cache fallback mode.")
            return
        try:
            from google.cloud import bigquery  # type: ignore

            self._bq_client = bigquery.Client(project=self.project)
            self._bq_available = True
        except Exception as exc:
            logger.warning("BigQuery client unavailable (%s); falling back to L1 cache.", exc)
            self._bq_available = False

    def _sync_from_bigquery_if_stale(self) -> None:
        if not self._bq_available or self._bq_client is None:
            return
        now = time.time()
        if (now - self._last_sync_ts) < self.cache_ttl:
            return
        try:
            table_ref = f"{self.project}.{self.dataset}.{self.table}"
            query = f"SELECT * FROM `{table_ref}` LIMIT 5000"
            rows = list(self._bq_client.query(query).result())
            for r in rows:
                item = ResourceRegistration(
                    id=r["id"],
                    type=ResourceType(r["type"]),
                    name=r["name"],
                    description=r["description"],
                    endpoint=r["endpoint"],
                    version=r.get("version") or "1.0.0",
                    tags=list(r.get("tags") or []),
                    capabilities=list(r.get("capabilities") or []),
                    provider=r.get("provider"),
                    location=r.get("location"),
                    schema_url=r.get("schema_url"),
                    metadata=json.loads(r["metadata_json"]) if r.get("metadata_json") else {},
                    created_at=float(r.get("created_at") or now),
                    health_status=r.get("health_status") or "healthy",
                )
                self._l1_cache.register(item)
            self._last_sync_ts = now
        except Exception as exc:
            logger.debug("BigQuery sync skipped: %s", exc)
            self._last_sync_ts = now

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        registered = self._l1_cache.register(res)
        if self._bq_available and self._bq_client is not None:
            try:
                table_ref = f"{self.project}.{self.dataset}.{self.table}"
                row = {
                    "id": registered.id,
                    "type": registered.type.value,
                    "name": registered.name,
                    "description": registered.description,
                    "endpoint": registered.endpoint,
                    "version": registered.version,
                    "tags": registered.tags,
                    "capabilities": registered.capabilities,
                    "provider": registered.provider,
                    "location": registered.location,
                    "schema_url": registered.schema_url,
                    "metadata_json": json.dumps(registered.metadata),
                    "created_at": registered.created_at,
                    "health_status": registered.health_status,
                }
                self._bq_client.insert_rows_json(table_ref, [row])
            except Exception as exc:
                logger.debug("BigQuery insert_rows_json deferred: %s", exc)
        return registered

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        self._sync_from_bigquery_if_stale()
        return self._l1_cache.get(res_id)

    def delete(self, res_id: str) -> bool:
        deleted = self._l1_cache.delete(res_id)
        if self._bq_available and self._bq_client is not None:
            try:
                from google.cloud import bigquery  # type: ignore

                table_ref = f"{self.project}.{self.dataset}.{self.table}"
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ScalarQueryParameter("res_id", "STRING", res_id)]
                )
                self._bq_client.query(
                    f"DELETE FROM `{table_ref}` WHERE id = @res_id", job_config=job_config
                )
            except Exception as exc:
                logger.debug("BigQuery delete deferred: %s", exc)
        return deleted

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        self._sync_from_bigquery_if_stale()
        return self._l1_cache.list_all(type_filter=type_filter)

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        self._sync_from_bigquery_if_stale()
        resp = self._l1_cache.search(query=query, type_filter=type_filter)
        resp.backend = self.backend_name
        return resp


class VertexAISearchBackend(StorageBackend):
    """
    Semantic Discovery Backend powered by Google Cloud Vertex AI Search (Discovery Engine)
    paired with a local SQLite catalog & TTL query cache for 100s+ RPS throughput.
    """

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        data_store_id: Optional[str] = None,
        local_store: Optional[StorageBackend] = None,
        cache_ttl: float = 60.0,
        search_client: Optional[object] = None,
    ):
        self.project = project or settings.google_cloud_project
        self.location = location or settings.vertex_search_location
        self.data_store_id = data_store_id or settings.vertex_search_datastore_id
        self.local_store = local_store or SQLiteBackend()
        self.cache_ttl = cache_ttl
        self._query_cache: Dict[Tuple[str, Optional[str]], Tuple[float, List[str]]] = {}
        self._search_client = search_client
        self._vertex_available = False
        self._init_vertex()

    @property
    def backend_name(self) -> str:
        return "vertex-ai-semantic" if self._vertex_available else "vertex-local-fallback"

    def _init_vertex(self) -> None:
        if self._search_client is not None:
            self._vertex_available = True
            return
        if not self.project or not self.data_store_id:
            return
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore

            self._search_client = discoveryengine.SearchServiceClient()
            self._vertex_available = True
        except Exception as exc:
            logger.warning("Vertex AI Search client unavailable (%s); using local FTS5 fallback.", exc)
            self._vertex_available = False

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        self._query_cache.clear()
        return self.local_store.register(res)

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        return self.local_store.get(res_id)

    def delete(self, res_id: str) -> bool:
        self._query_cache.clear()
        return self.local_store.delete(res_id)

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        return self.local_store.list_all(type_filter=type_filter)

    def semantic_rank_ids(self, query: str, type_filter: Optional[ResourceType] = None) -> List[str]:
        """Queries Vertex AI Discovery Engine (with TTL cache) for matching resource IDs."""
        if not self._vertex_available or self._search_client is None or not query.strip():
            return []

        cache_key = (query.strip().lower(), type_filter.value if type_filter else None)
        now = time.time()
        cached = self._query_cache.get(cache_key)
        if cached and (now - cached[0]) < self.cache_ttl:
            return cached[1]

        matched_ids: List[str] = []
        try:
            serving_config = (
                f"projects/{self.project}/locations/{self.location}/"
                f"collections/default_collection/dataStores/{self.data_store_id}/"
                f"servingConfigs/default_search"
            )
            request = {
                "serving_config": serving_config,
                "query": query,
                "page_size": 10,
            }
            response = self._search_client.search(request=request)
            for result in getattr(response, "results", []):
                doc = getattr(result, "document", None)
                doc_id = getattr(doc, "id", None) if doc else None
                if doc_id:
                    matched_ids.append(str(doc_id))
        except Exception as exc:
            logger.debug("Vertex AI Search call failed: %s", exc)

        self._query_cache[cache_key] = (now, matched_ids)
        return matched_ids

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        start_time = time.perf_counter()
        base_resp = self.local_store.search(query=query, type_filter=type_filter)
        results_by_id = {r.id: r for r in base_resp.results}

        if query.strip() and self._vertex_available:
            semantic_ids = self.semantic_rank_ids(query, type_filter=type_filter)
            merged: List[ResourceRegistration] = []
            seen = set()
            for rid in semantic_ids:
                item = results_by_id.get(rid) or self.local_store.get(rid)
                if item and (not type_filter or item.type == type_filter):
                    merged.append(item)
                    seen.add(item.id)
            for item in base_resp.results:
                if item.id not in seen:
                    merged.append(item)
            results = merged
        else:
            results = base_resp.results

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return SearchResponse(
            query=query,
            type_filter=type_filter.value if type_filter else None,
            total_results=len(results),
            execution_time_ms=round(elapsed_ms, 3),
            results=results,
            backend=self.backend_name,
        )


class HybridBackend(StorageBackend):
    """
    Tiered Enterprise Backend:
    - Primary Read/Search: Local SQLite WAL + FTS5 (<1ms latency, 1,000+ RPS)
    - Semantic Expansion: Vertex AI Search fallback when lexical recall < min_lexical_results
    - Cloud Persistence / Audit: BigQuery write-behind sync
    """

    def __init__(
        self,
        local: Optional[SQLiteBackend] = None,
        semantic: Optional[VertexAISearchBackend] = None,
        audit_bq: Optional[BigQueryBackend] = None,
        min_lexical_results: int = 3,
    ):
        self.local = local or SQLiteBackend()
        self.semantic = semantic or VertexAISearchBackend(local_store=self.local)
        self.audit_bq = audit_bq or BigQueryBackend(seed_defaults=False)
        self.min_lexical_results = min_lexical_results

    @property
    def backend_name(self) -> str:
        return "hybrid-sqlite-vertex-bq"

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        registered = self.local.register(res)
        if self.audit_bq._bq_available:
            self.audit_bq.register(registered)
        return registered

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        return self.local.get(res_id)

    def delete(self, res_id: str) -> bool:
        deleted = self.local.delete(res_id)
        if self.audit_bq._bq_available:
            self.audit_bq.delete(res_id)
        return deleted

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        return self.local.list_all(type_filter=type_filter)

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        start_time = time.perf_counter()
        resp = self.local.search(query=query, type_filter=type_filter)
        if query.strip() and resp.total_results < self.min_lexical_results and self.semantic._vertex_available:
            resp = self.semantic.search(query=query, type_filter=type_filter)
        resp.execution_time_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
        resp.backend = self.backend_name
        return resp

    def close(self) -> None:
        self.local.close()


def create_backend_from_config(cfg: Optional[ARDSConfig] = None) -> StorageBackend:
    """Factory that builds the configured StorageBackend from ARDSConfig / .env."""
    c = cfg or settings
    mode = (c.backend or "sqlite").lower()
    if mode == "bigquery":
        return BigQueryBackend(
            project=c.google_cloud_project,
            dataset=c.bq_dataset,
            table=c.bq_table,
            cache_ttl=c.bq_cache_ttl_seconds,
            seed_defaults=c.seed_defaults,
        )
    if mode == "vertex":
        local = SQLiteBackend(db_path=c.sqlite_path, seed_defaults=c.seed_defaults)
        return VertexAISearchBackend(
            project=c.google_cloud_project,
            location=c.vertex_search_location,
            data_store_id=c.vertex_search_datastore_id,
            local_store=local,
        )
    if mode == "hybrid":
        local = SQLiteBackend(db_path=c.sqlite_path, seed_defaults=c.seed_defaults)
        return HybridBackend(
            local=local,
            semantic=VertexAISearchBackend(
                project=c.google_cloud_project,
                location=c.vertex_search_location,
                data_store_id=c.vertex_search_datastore_id,
                local_store=local,
            ),
            audit_bq=BigQueryBackend(
                project=c.google_cloud_project,
                dataset=c.bq_dataset,
                table=c.bq_table,
                cache_ttl=c.bq_cache_ttl_seconds,
                seed_defaults=False,
            ),
        )
    return SQLiteBackend(db_path=c.sqlite_path, seed_defaults=c.seed_defaults)
