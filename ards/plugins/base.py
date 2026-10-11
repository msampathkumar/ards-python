"""ARDS Plugin Architecture: Base Plugin Interface and Hook Lifecycle."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from ards.models import ResourceRegistration, SearchResponse


class ARDSPlugin(ABC):
    """Abstract Base Class for all ARDS ecosystem plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    async def on_startup(self) -> None:
        """Executed during FastAPI startup lifecycle."""
        pass

    async def on_shutdown(self) -> None:
        """Executed during FastAPI shutdown lifecycle."""
        pass

    async def pre_registration(self, resource: ResourceRegistration) -> ResourceRegistration:
        """Filter/mutate resource before registration."""
        return resource

    async def post_registration(self, resource: ResourceRegistration) -> None:
        """Hook called after successful registration (e.g., sync to external index)."""
        pass

    async def on_search(self, query: str, response: SearchResponse) -> SearchResponse:
        """Hook to augment search results (e.g., hybrid vector reranking)."""
        return response


class PluginManager:
    """Manages plugin discovery, lifecycle hooks, and safe execution."""

    def __init__(self):
        self._plugins: Dict[str, ARDSPlugin] = {}

    def register_plugin(self, plugin: ARDSPlugin) -> None:
        self._plugins[plugin.name] = plugin

    def get_plugin(self, name: str) -> Optional[ARDSPlugin]:
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, str]]:
        return [{"name": p.name, "version": p.version} for p in self._plugins.values()]

    async def trigger_post_registration(self, resource: ResourceRegistration) -> None:
        for p in self._plugins.values():
            try:
                await p.post_registration(resource)
            except Exception as e:
                # 2nd-order fault isolation: plugin failures must never crash core registry
                pass

    async def trigger_on_search(self, query: str, response: SearchResponse) -> SearchResponse:
        for p in self._plugins.values():
            try:
                response = await p.on_search(query, response)
            except Exception:
                pass
        return response


plugin_manager = PluginManager()
