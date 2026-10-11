"""ARDS Registry SDK Facade with Pluggable Storage Backends and Subscription Hooks."""

import inspect
import re
import threading
from typing import Any, Callable, Dict, List, Optional
import time

from ards.config import ARDSConfig, settings
from ards.events import EventBus, create_event_bus
from ards.models import ResourceRegistration, ResourceType, SearchResponse
from ards.storage import SQLiteBackend, StorageBackend, create_backend_from_config

RegistrationCallback = Callable[[ResourceRegistration], Any]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def make_resource_id(res_type: ResourceType, name: str) -> str:
    """Builds a safe, stable id like 'agent-tokyo-logistics-hub' from a display name."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")[:100] or "resource"
    return f"{res_type.value}-{slug}"


class Registry:
    """
    Core ARDS Registry SDK class.
    - By default (`Registry()`), uses a high-speed local `SQLiteBackend` (WAL + FTS5 BM25).
    - Supports pluggable backends: `SQLiteBackend`, `BigQueryBackend`, `VertexAISearchBackend`, `HybridBackend`.
    - Provides simple subscription decorators:
        `@registry.on_registration` -> fires once when a NEW resource joins.
        `@registry.on_update`       -> fires when an existing resource changes (e.g. health status).
    """

    def __init__(
        self,
        backend: Optional[StorageBackend] = None,
        db_path: Optional[str] = None,
        seed_defaults: Optional[bool] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[ARDSConfig] = None,
    ):
        self.config = config or settings
        seed = seed_defaults if seed_defaults is not None else self.config.seed_defaults

        if backend is not None:
            self.backend = backend
        elif db_path is not None:
            self.backend = SQLiteBackend(db_path=db_path, seed_defaults=seed)
        else:
            self.backend = create_backend_from_config(self.config)

        self.event_bus = event_bus or create_event_bus(self.config)
        self._registration_callbacks: List[RegistrationCallback] = []
        self._update_callbacks: List[RegistrationCallback] = []

        # Wire EventBus events to local callbacks
        self.event_bus.subscribe("resource.registered", self._handle_bus_registration)
        self.event_bus.subscribe("resource.updated", self._handle_bus_update)

    @staticmethod
    async def _dispatch(callbacks: List[RegistrationCallback], payload: Dict[str, Any]) -> None:
        try:
            res = ResourceRegistration(**payload)
        except Exception:
            return
        for cb in list(callbacks):
            out = cb(res)
            if inspect.isawaitable(out):
                await out

    async def _handle_bus_registration(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._dispatch(self._registration_callbacks, payload)

    async def _handle_bus_update(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._dispatch(self._update_callbacks, payload)

    def on_registration(self, func: RegistrationCallback) -> RegistrationCallback:
        """
        Decorator or method to subscribe to newly registered resources (fires once per new resource).

        Example:
            @registry.on_registration
            async def handle_new_agent(res: ResourceRegistration):
                print(f"New resource: {res.name}")
        """
        self._registration_callbacks.append(func)
        return func

    def on_update(self, func: RegistrationCallback) -> RegistrationCallback:
        """Decorator to subscribe to changes of existing resources (re-registration, health status updates)."""
        self._update_callbacks.append(func)
        return func

    def subscribe(self, callback: RegistrationCallback) -> RegistrationCallback:
        """Alias for `on_registration`."""
        return self.on_registration(callback)

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        if not res.created_at:
            res.created_at = time.time()
        is_new = self.backend.get(res.id) is None
        saved = self.backend.register(res)
        # Deprecated: published "resource.registered" on every write, so subscribers were
        # flooded on each Ops Brain health sweep. New vs. update are now separate topics.
        # self.event_bus.publish_sync("resource.registered", saved.model_dump())
        topic = "resource.registered" if is_new else "resource.updated"
        self.event_bus.publish_sync(topic, saved.model_dump())
        return saved

    def submit(
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
        """
        Simple 1-call helper for users & agents to submit a resource to the registry without boilerplate.
        """
        res_type = ResourceType(type.lower()) if isinstance(type, str) else type
        item = ResourceRegistration(
            id=id or make_resource_id(res_type, name),
            type=res_type,
            name=name,
            description=description or f"{name} ({res_type.value.upper()}) registered via ARDS SDK.",
            endpoint=endpoint,
            version=version,
            capabilities=capabilities or [],
            tags=tags or [],
            location=location,
            provider=provider,
            schema_url=schema_url,
            metadata=metadata or {},
        )
        return self.register(item)

    def get(self, res_id: str) -> Optional[ResourceRegistration]:
        return self.backend.get(res_id)

    def delete(self, res_id: str) -> bool:
        deleted = self.backend.delete(res_id)
        if deleted:
            self.event_bus.publish_sync("resource.deleted", {"id": res_id})
        return deleted

    def list_all(self, type_filter: Optional[ResourceType] = None) -> List[ResourceRegistration]:
        return self.backend.list_all(type_filter=type_filter)

    def search(
        self,
        query: str = "",
        type_filter: Optional[ResourceType] = None,
        limit: Optional[int] = None,
    ) -> SearchResponse:
        """Searches the registry. `total_results` is the full match count; `limit` caps returned items."""
        resp = self.backend.search(query=query, type_filter=type_filter)
        if limit is not None and limit >= 0:
            resp.results = resp.results[:limit]
        return resp

    def close(self) -> None:
        self.backend.close()


class _DefaultRegistry:
    """Lazy proxy for the process-wide default `Registry`.

    The real Registry (and its SQLite file) is only created on first use, so `import ards`
    has no side effects for users who only need `ARDSClient`. Call `configure()` to replace it.
    """

    def __init__(self) -> None:
        self._instance: Optional[Registry] = None
        self._lock = threading.Lock()

    def get_instance(self) -> Registry:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = Registry()
        return self._instance

    def configure(self, **kwargs: Any) -> Registry:
        """Replace the default registry, e.g. `default_registry.configure(backend=SQLiteBackend(':memory:'))`.

        Note: subscriptions made on the previous instance are not carried over.
        """
        with self._lock:
            if self._instance is not None:
                self._instance.close()
            self._instance = Registry(**kwargs)
        return self._instance

    def reset(self) -> None:
        """Drop the current instance; the next use rebuilds it from the (possibly reloaded) settings."""
        with self._lock:
            if self._instance is not None:
                self._instance.close()
            self._instance = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.get_instance(), name)


# Deprecated in-memory dictionary implementation (replaced by pluggable StorageBackend & SQLite FTS5):
# class Registry:
#     def __init__(self):
#         self._resources: Dict[str, ResourceRegistration] = {}
#         self._seed_default_catalog()

default_registry = _DefaultRegistry()
# Backward-compatible alias used by `from ards.registry import registry`.
registry = default_registry
