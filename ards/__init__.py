"""ARDS Python SDK: Agent & Resource Directory Service."""

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("ards-python")
except Exception:  # pragma: no cover - not installed (e.g. running from a source checkout)
    __version__ = "0.0.0+local"

from typing import Any, Callable, Dict, List, Optional, TypeVar

from ards.client.client import ARDSClient
from ards.config import ARDSConfig, load_dotenv, reload_settings, settings
from ards.events import (
    EventBus,
    GCPPubSubEventBus,
    InMemoryEventBus,
    SQLiteEventBus,
    create_event_bus,
)
from ards.models import AgentCard, ResourceRegistration, ResourceType, SearchResponse
from ards.ops import ARDSOpsBrain
# Deprecated: `from ards.registry import Registry, registry` shadowed the `ards.registry` submodule.
from ards.registry import Registry, default_registry, make_resource_id
from ards.storage import (
    BigQueryBackend,
    HybridBackend,
    SQLiteBackend,
    StorageBackend,
    VertexAISearchBackend,
    create_backend_from_config,
)

T = TypeVar("T")


async def submit(
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
    server_url: Optional[str] = None,
) -> ResourceRegistration:
    """
    Top-level 1-line SDK submission helper for humans and agents.
    - If `server_url` is provided, submits over HTTP via `ARDSClient`.
    - Otherwise, registers directly in the active `registry` instance.
    """
    if server_url:
        async with ARDSClient(base_url=server_url) as client:
            return await client.submit(
                name=name,
                endpoint=endpoint,
                type=type,
                description=description,
                id=id,
                capabilities=capabilities,
                tags=tags,
                location=location,
                provider=provider,
                version=version,
                schema_url=schema_url,
                metadata=metadata,
            )
    return default_registry.submit(
        name=name,
        endpoint=endpoint,
        type=type,
        description=description,
        id=id,
        capabilities=capabilities,
        tags=tags,
        location=location,
        provider=provider,
        version=version,
        schema_url=schema_url,
        metadata=metadata,
    )


def register_agent(
    name: str,
    endpoint: str,
    id: Optional[str] = None,
    description: str = "",
    capabilities: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    location: Optional[str] = None,
    provider: Optional[str] = None,
    version: str = "1.0.0",
    schema_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    target_registry: Optional[Registry] = None,
) -> Callable[[T], T]:
    """
    Class/function decorator for agent builders to automatically register an Agent in ARDS.

    Example:
        @ards.register_agent(name="Osaka Hub", endpoint="http://localhost:8009/a2a", tags=["apac"])
        class OsakaAgent:
            ...
    """
    reg = target_registry or default_registry

    def decorator(obj: T) -> T:
        doc = description or (getattr(obj, "__doc__", None) or "").strip()
        reg.submit(
            name=name,
            endpoint=endpoint,
            type=ResourceType.AGENT,
            description=doc,
            id=id,
            capabilities=capabilities,
            tags=tags,
            location=location,
            provider=provider,
            version=version,
            schema_url=schema_url,
            metadata=metadata,
        )
        return obj

    return decorator


def on_registration(func: Callable[[ResourceRegistration], Any]) -> Callable[[ResourceRegistration], Any]:
    """Top-level decorator to subscribe to new registrations on the default registry."""
    return default_registry.on_registration(func)


def on_update(func: Callable[[ResourceRegistration], Any]) -> Callable[[ResourceRegistration], Any]:
    """Top-level decorator to subscribe to updates (e.g. health changes) on the default registry."""
    return default_registry.on_update(func)


__all__ = [
    "ARDSClient",
    "ARDSConfig",
    "ARDSOpsBrain",
    "AgentCard",
    "BigQueryBackend",
    "EventBus",
    "GCPPubSubEventBus",
    "HybridBackend",
    "InMemoryEventBus",
    "Registry",
    "ResourceRegistration",
    "ResourceType",
    "SQLiteBackend",
    "SQLiteEventBus",
    "SearchResponse",
    "StorageBackend",
    "VertexAISearchBackend",
    "create_backend_from_config",
    "create_event_bus",
    "load_dotenv",
    "on_registration",
    "register_agent",
    "default_registry",
    "make_resource_id",
    "on_update",
    "reload_settings",
    "__version__",
    "settings",
    "submit",
]
