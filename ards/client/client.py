"""Production Client SDK for ARDS."""

import httpx
from typing import List, Optional, Dict, Any
from ards.models import ResourceRegistration, ResourceType, SearchResponse


class ARDSClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        params: Dict[str, Any] = {"q": query}
        if type_filter:
            params["type"] = type_filter.value
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            resp = await client.get("/api/v1/search", params=params, timeout=10.0)
            resp.raise_for_status()
            return SearchResponse(**resp.json())

    async def register(self, resource: ResourceRegistration) -> ResourceRegistration:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            resp = await client.post("/api/v1/resources", json=resource.model_dump(), timeout=10.0)
            resp.raise_for_status()
            return ResourceRegistration(**resp.json())

    async def get_resource(self, res_id: str) -> Optional[ResourceRegistration]:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            resp = await client.get(f"/api/v1/resources/{res_id}", timeout=10.0)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return ResourceRegistration(**resp.json())
