"""Tests for plugin fault isolation and error logging (ap-vzxx)."""

import logging

import pytest

from ards.models import ResourceRegistration, ResourceType, SearchResponse
from ards.plugins.base import ARDSPlugin, PluginManager


class ExplodingPlugin(ARDSPlugin):
    """Plugin whose hooks always raise, to exercise fault isolation."""

    @property
    def name(self) -> str:
        return "exploding"

    @property
    def version(self) -> str:
        return "0.0.1"

    async def post_registration(self, resource):
        raise RuntimeError("boom-post")

    async def on_search(self, query, response):
        raise RuntimeError("boom-search")


def _resource() -> ResourceRegistration:
    return ResourceRegistration(
        id="r1",
        type=ResourceType.AGENT,
        name="R1",
        description="test resource",
        endpoint="http://example.test/a2a",
    )


@pytest.mark.asyncio
async def test_post_registration_failure_is_logged_not_raised(caplog):
    pm = PluginManager()
    pm.register_plugin(ExplodingPlugin())
    with caplog.at_level(logging.ERROR, logger="ards.plugins.base"):
        await pm.trigger_post_registration(_resource())
    assert any("exploding failed in post_registration" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_on_search_failure_is_logged_and_response_returned(caplog):
    pm = PluginManager()
    pm.register_plugin(ExplodingPlugin())
    original = SearchResponse(query="q", type_filter=None, total_results=0, execution_time_ms=0.0, results=[])
    with caplog.at_level(logging.ERROR, logger="ards.plugins.base"):
        result = await pm.trigger_on_search("q", original)
    assert result == original
    assert any("exploding failed in on_search" in r.getMessage() for r in caplog.records)
