"""ARDS Registry SDK Facade with Pluggable Storage Backends and Subscription Hooks."""

import inspect
from typing import Any, Callable, Dict, List, Optional
import time

from ards.config import ARDSConfig, settings
from ards.events import EventBus, create_event_bus
from ards.models import ResourceRegistration, ResourceType, SearchResponse
from ards.storage import SQLiteBackend, StorageBackend, create_backend_from_config

RegistrationCallback = Callable[[ResourceRegistration], Any]


class Registry:
    """
    Core ARDS Registry SDK class.
    - By default (`Registry()`), uses a high-speed local `SQLiteBackend` (WAL + FTS5 BM25).
    - Supports pluggable backends: `SQLiteBackend`, `BigQueryBackend`, `VertexAISearchBackend`, `HybridBackend`.
    - Provides a simple `@registry.on_registration` subscription decorator for agents & orchestrators.
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

        # Wire EventBus "resource.registered" events to local callbacks
        self.event_bus.subscribe("resource.registered", self._handle_bus_registration)

    async def _handle_bus_registration(self, topic: str, payload: Dict[str, Any]) -> None:
        try:
            res = ResourceRegistration(**payload)
        except Exception:
            return
        for cb in list(self._registration_callbacks):
            out = cb(res)
            if inspect.isawaitable(out):
                await out

    def on_registration(self, func: RegistrationCallback) -> RegistrationCallback:
        """
        Decorator or method to subscribe to newly registered resources.

        Example:
            @registry.on_registration
            async def handle_new_agent(res: ResourceRegistration):
                print(f"New resource: {res.name}")
        """
        self._registration_callbacks.append(func)
        return func

    def subscribe(self, callback: RegistrationCallback) -> RegistrationCallback:
        """Alias for `on_registration`."""
        return self.on_registration(callback)

    def register(self, res: ResourceRegistration) -> ResourceRegistration:
        if not res.created_at:
            res.created_at = time.time()
        saved = self.backend.register(res)
        self.event_bus.publish_sync("resource.registered", saved.model_dump())
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
        slug = id or f"{res_type.value}-{name.lower().replace(' ', '-')}"
        item = ResourceRegistration(
            id=slug,
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

    def search(self, query: str = "", type_filter: Optional[ResourceType] = None) -> SearchResponse:
        return self.backend.search(query=query, type_filter=type_filter)


# Deprecated in-memory dictionary implementation (replaced by pluggable StorageBackend & SQLite FTS5):
# class Registry:
#     def __init__(self):
#         self._resources: Dict[str, ResourceRegistration] = {}
#         self._seed_default_catalog()

registry = Registry()
