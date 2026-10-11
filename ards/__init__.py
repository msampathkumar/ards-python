"""ARDS Python SDK: Agent & Resource Directory Service."""

from typing import Any, Callable, Dict, List, Optional, TypeVar

from ards.client.client import ARDSClient
from ards.config import ARDSConfig, load_dotenv, settings
from ards.events import (
    EventBus,
    GCPPubSubEventBus,
    InMemoryEventBus,
    SQLiteEventBus,
    create_event_bus,
)
from ards.models import AgentCard, ResourceRegistration, ResourceType, SearchResponse
from ards.ops import ARDSOpsBrain
from ards.registry import Registry, registry
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
    return registry.submit(
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
    reg = target_registry or registry

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
    """Top-level decorator to subscribe to new registrations on the default `registry`."""
    return registry.on_registration(func)


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
    "registry",
    "settings",
    "submit",
]
