"""Google Cloud Platform Plugins for ARDS: BigQuery Analytics and Vertex AI Agent Search."""

import asyncio
import logging
import os
import time
from typing import Dict, Any, List, Optional, Tuple
from ards.config import settings
from ards.models import ResourceRegistration, SearchResponse
from ards.plugins.base import ARDSPlugin

logger = logging.getLogger("ards.plugins.gcp")


class BigQueryRegistryAuditPlugin(ARDSPlugin):
    """
    Exports registration audit logs, query volume, and capability metrics
    into Google Cloud BigQuery for enterprise observability and BI dashboards.
    Gracefully auto-disables when GOOGLE_CLOUD_PROJECT is not configured.
    """

    def __init__(
        self,
        dataset_id: Optional[str] = None,
        table_id: Optional[str] = None,
        project_id: Optional[str] = None,
        bq_client: Optional[object] = None,
    ):
        self.dataset_id = dataset_id or settings.bq_dataset or "ards_analytics"
        self.table_id = table_id or settings.bq_audit_table or "registrations_log"
        self._gcp_project = project_id or settings.google_cloud_project
        self._bq_client = bq_client
        self._enabled = False
        self._init_client()

    def _init_client(self) -> None:
        if self._bq_client is not None:
            self._enabled = True
            return
        if not self._gcp_project:
            return
        try:
            from google.cloud import bigquery  # type: ignore

            self._bq_client = bigquery.Client(project=self._gcp_project)
            self._enabled = True
        except Exception as exc:
            logger.debug("BigQueryRegistryAuditPlugin disabled: %s", exc)
            self._enabled = False

    @property
    def name(self) -> str:
        return "gcp-bigquery-audit"

    @property
    def version(self) -> str:
        return "1.1.0"

    async def post_registration(self, resource: ResourceRegistration) -> None:
        """
        Streams registration event into BigQuery asynchronously without blocking the serving thread.
        Falls back gracefully if running in local/offline environments.
        """
        if not self._enabled or self._bq_client is None:
            return None

        row_payload = {
            "resource_id": resource.id,
            "resource_type": resource.type.value,
            "name": resource.name,
            "location": resource.location or "GLOBAL",
            "endpoint": resource.endpoint,
            "capabilities": resource.capabilities,
            "tags": resource.tags,
            "registered_at_timestamp": resource.created_at,
        }
        table_ref = f"{self._gcp_project}.{self.dataset_id}.{self.table_id}"
        try:
            await asyncio.to_thread(self._bq_client.insert_rows_json, table_ref, [row_payload])
        except Exception as exc:
            logger.debug("BigQuery audit stream skipped: %s", exc)
        return None


class VertexAISearchPlugin(ARDSPlugin):
    """
    Integrates with Google Cloud Vertex AI Search & Vector Search for
    enterprise-grade hybrid semantic matchmaking and natural language query expansion.
    Includes an in-memory TTL cache for high-RPS serving and auto-disables when GCP is not configured.
    """

    def __init__(
        self,
        data_store_id: Optional[str] = None,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        cache_ttl: float = 60.0,
        search_client: Optional[object] = None,
    ):
        self.data_store_id = data_store_id or settings.vertex_search_datastore_id
        self.project_id = project_id or settings.google_cloud_project
        self.location = location or settings.vertex_search_location or "global"
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[float, List[str]]] = {}
        self._search_client = search_client
        self._enabled = False
        self._init_client()

    def _init_client(self) -> None:
        if self._search_client is not None:
            self._enabled = True
            return
        if not self.project_id or not self.data_store_id:
            return
        try:
            from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore

            self._search_client = discoveryengine.SearchServiceClient()
            self._enabled = True
        except Exception as exc:
            logger.debug("VertexAISearchPlugin disabled: %s", exc)
            self._enabled = False

    @property
    def name(self) -> str:
        return "gcp-vertex-ai-search"

    @property
    def version(self) -> str:
        return "1.1.0"

    async def on_search(self, query: str, response: SearchResponse) -> SearchResponse:
        """
        Enhances search responses using semantic vector ranking when query has low lexical recall.
        """
        if not self._enabled or self._search_client is None or not query.strip() or response.total_results >= 3:
            return response

        from ards.registry import registry

        q_key = query.strip().lower()
        now = time.time()
        cached = self._cache.get(q_key)
        if cached and (now - cached[0]) < self.cache_ttl:
            matched_ids = cached[1]
        else:
            matched_ids = []
            try:
                serving_config = (
                    f"projects/{self.project_id}/locations/{self.location}/"
                    f"collections/default_collection/dataStores/{self.data_store_id}/"
                    f"servingConfigs/default_search"
                )
                req = {"serving_config": serving_config, "query": query, "page_size": 5}
                res = await asyncio.to_thread(self._search_client.search, request=req)
                for item in getattr(res, "results", []):
                    doc = getattr(item, "document", None)
                    doc_id = getattr(doc, "id", None) if doc else None
                    if doc_id:
                        matched_ids.append(str(doc_id))
                self._cache[q_key] = (now, matched_ids)
            except Exception as exc:
                logger.debug("VertexAISearchPlugin lookup skipped: %s", exc)
                return response

        existing_ids = {r.id for r in response.results}
        for rid in matched_ids:
            if rid not in existing_ids:
                found = registry.get(rid)
                if found:
                    response.results.append(found)
                    existing_ids.add(rid)
        response.total_results = len(response.results)
        return response
