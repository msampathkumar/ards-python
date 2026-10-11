"""Production Client SDK for ARDS with Persistent Connection Pooling & 1-Line Helpers."""

import time
import httpx
from typing import List, Optional, Dict, Any, Tuple
from ards.config import settings
from ards.models import ResourceRegistration, ResourceType, SearchResponse


class ARDSClient:
    """
    Asynchronous ARDS Client SDK optimized for high-RPS multi-agent discovery.
    - Reuses a persistent HTTP connection pool (`max_connections=200`, `max_keepalive_connections=50`).
    - Optional client-side TTL cache (`cache_ttl`) for ultra-fast repeated discovery calls.
    - Provides a simple 1-call `.submit(name=..., endpoint=...)` method for agents & humans.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        cache_ttl: float = 0.0,
        timeout: float = 10.0,
        max_connections: int = 200,
        max_keepalive_connections: int = 50,
        retries: int = 2,
    ):
        default_url = f"http://{settings.host}:{settings.port}"
        self.base_url = (base_url or default_url).rstrip("/")
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.retries = retries
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._search_cache: Dict[Tuple[str, Optional[str]], Tuple[float, SearchResponse]] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                limits=self._limits,
                # Retries only connection-level failures (safe for all methods); HTTP errors are not retried.
                transport=httpx.AsyncHTTPTransport(retries=self.retries, limits=self._limits),
            )
        return self._client

    async def __aenter__(self) -> "ARDSClient":
        self._get_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        cache_key = (query, type_filter.value if type_filter else None)
        if self.cache_ttl > 0:
            cached = self._search_cache.get(cache_key)
            if cached and (time.time() - cached[0]) < self.cache_ttl:
                return cached[1]

        params: Dict[str, Any] = {"q": query}
        if type_filter:
            params["type"] = type_filter.value
        client = self._get_client()
        resp = await client.get("/api/v1/search", params=params)
        resp.raise_for_status()
        parsed = SearchResponse(**resp.json())
        if self.cache_ttl > 0:
            self._search_cache[cache_key] = (time.time(), parsed)
        return parsed

    async def register(self, resource: ResourceRegistration) -> ResourceRegistration:
        self._search_cache.clear()
        client = self._get_client()
        resp = await client.post("/api/v1/resources", json=resource.model_dump())
        resp.raise_for_status()
        return ResourceRegistration(**resp.json())

    async def submit(
        self,
        name: str,
        endpoint: str,
        type: str | ResourceType = ResourceType.AGENT,
        description: str = "",
        id: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        location: Optional[str] = None,
        provider: Optional[str] = None,
        version: str = "1.0.0",
        schema_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResourceRegistration:
        """1-line ergonomic submission helper over HTTP."""
        res_type = ResourceType(type.lower()) if isinstance(type, str) else type
        slug = id or f"{res_type.value}-{name.lower().replace(' ', '-')}"
        resource = ResourceRegistration(
            id=slug,
            type=res_type,
            name=name,
            description=description or f"{name} ({res_type.value.upper()}) submitted via ARDSClient.",
            endpoint=endpoint,
            version=version,
            capabilities=capabilities or [],
            tags=tags or [],
            location=location,
            provider=provider,
            schema_url=schema_url,
            metadata=metadata or {},
        )
        return await self.register(resource)

    async def get_resource(self, res_id: str) -> Optional[ResourceRegistration]:
        client = self._get_client()
        resp = await client.get(f"/api/v1/resources/{res_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return ResourceRegistration(**resp.json())
