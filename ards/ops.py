"""ARDS "Brain of Ops" (`ARDSOpsBrain`): Verification, Periodic Health Sweeping, and `--auto-clean`.

- Default Mode (`ARDS_PUBSUB_ENABLED=false`, `ARDS_MODE=combined`):
  Runs inside the same process alongside the Frontend server.
- Split Mode (`ARDS_PUBSUB_ENABLED=true`):
  Frontend publishes `resource.submitted` events to the `EventBus` (SQLite Queue or Google Cloud Pub/Sub),
  and a standalone Ops Brain worker consumes them, validates endpoints, updates health status,
  and automatically cleans dead/unreachable entries when `--auto-clean` (`auto_clean=True`) is enabled.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from ards.config import ARDSConfig, settings
from ards.events import EventBus
from ards.models import ResourceRegistration, ResourceType
from ards.registry import Registry
from ards.server.verifier import RegistrationVerifier, verifier as default_verifier

logger = logging.getLogger("ards.ops")


class ARDSOpsBrain:
    """
    Autonomous Operations Engine ("Brain of Ops") for ARDS.
    Responsibilities:
    1. Verify submitted registrations (inline or consumed via Pub/Sub queue).
    2. Periodically sweep and validate live endpoints in the registry.
    3. Evict non-working resources when `auto_clean=True` (`--auto-clean`).
    """

    def __init__(
        self,
        registry: Registry,
        verifier: Optional[RegistrationVerifier] = None,
        event_bus: Optional[EventBus] = None,
        auto_clean: Optional[bool] = None,
        sweep_interval_seconds: Optional[float] = None,
        max_failures: Optional[int] = None,
        protect_seed_data: Optional[bool] = None,
        allow_local: bool = True,
        config: Optional[ARDSConfig] = None,
    ):
        self.config = config or settings
        self.registry = registry
        self.verifier = verifier or default_verifier
        self.event_bus = event_bus or registry.event_bus
        self.auto_clean = auto_clean if auto_clean is not None else self.config.auto_clean
        self.sweep_interval_seconds = (
            sweep_interval_seconds
            if sweep_interval_seconds is not None
            else self.config.sweep_interval_seconds
        )
        self.max_failures = max_failures if max_failures is not None else self.config.max_failures
        self.protect_seed_data = (
            protect_seed_data if protect_seed_data is not None else self.config.protect_seed_data
        )
        self.allow_local = allow_local

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.stats: Dict[str, Any] = {
            "sweeps_completed": 0,
            "resources_verified": 0,
            "resources_evicted": 0,
            "last_sweep_at": None,
        }

        # Subscribe to async registration submissions from Pub/Sub bus
        self.event_bus.subscribe("resource.submitted", self._on_submitted_event)

    async def _on_submitted_event(self, topic: str, payload: Dict[str, Any]) -> None:
        try:
            res = ResourceRegistration(**payload)
            await self.verify_and_record(res)
        except Exception as exc:
            logger.debug("OpsBrain failed processing submitted resource: %s", exc)

    async def submit_for_verification(self, res: ResourceRegistration) -> ResourceRegistration:
        """
        Used by the Frontend server on registration intake:
        - If Pub/Sub is disabled (default simple mode), verifies and registers immediately inline.
        - If Pub/Sub is enabled, records with `provisional` status and publishes `resource.submitted`
          for the Ops Brain worker to verify asynchronously.
        """
        if not self.config.pubsub_enabled or self.event_bus.provider_name == "memory":
            return await self.verify_and_record(res)

        res.health_status = "provisional"
        res.verification_message = "Queued for Ops Brain verification via Pub/Sub."
        saved = self.registry.register(res)
        await self.event_bus.publish("resource.submitted", saved.model_dump())
        return saved

    async def verify_and_record(self, res: ResourceRegistration) -> ResourceRegistration:
        """Validates a resource via RegistrationVerifier and updates its status in the registry."""
        ok, msg = await self.verifier.verify(res, allow_local=self.allow_local)
        now = time.time()
        res.last_verified_at = now
        res.verification_message = msg

        if not ok:
            res.consecutive_failures += 1
            res.health_status = "unreachable"
            if self.auto_clean and res.consecutive_failures >= self.max_failures:
                self.registry.delete(res.id)
                self.stats["resources_evicted"] += 1
                await self.event_bus.publish("resource.evicted", {"id": res.id, "reason": msg})
                return res
        else:
            res.consecutive_failures = 0
            res.health_status = "healthy" if msg.startswith("VERIFIED:") else "provisional"

        saved = self.registry.register(res)
        self.stats["resources_verified"] += 1
        await self.event_bus.publish("resource.verified", saved.model_dump())
        return saved

    async def probe_endpoint_live(self, res: ResourceRegistration) -> bool:
        """Actively checks whether a registered resource endpoint is reachable and healthy."""
        if res.type in (ResourceType.SKILL, ResourceType.PLUGIN):
            return True

        probe_url = res.endpoint
        if res.type == ResourceType.AGENT and res.schema_url:
            probe_url = res.schema_url

        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                resp = await client.get(probe_url)
                return resp.status_code < 500
        except Exception:
            return False

    async def sweep_once(self) -> Dict[str, Any]:
        """
        Runs a full validation pass over all registered resources (plus drains any pending Pub/Sub events).
        When `auto_clean=True` (`--auto-clean`), evicts resources that exceed `max_failures`.
        """
        await self.event_bus.poll_once()
        items = self.registry.list_all()
        sem = asyncio.Semaphore(10)

        checked = 0
        healthy_count = 0
        degraded_count = 0
        evicted_ids: List[str] = []

        async def _check_item(item: ResourceRegistration) -> None:
            nonlocal checked, healthy_count, degraded_count
            if self.protect_seed_data and item.metadata.get("seed") is True:
                healthy_count += 1
                return

            async with sem:
                checked += 1
                ok, msg = await self.verifier.verify(item, allow_local=self.allow_local)
                reachable = ok and await self.probe_endpoint_live(item)
                now = time.time()
                item.last_verified_at = now

                if reachable:
                    item.consecutive_failures = 0
                    item.health_status = "healthy"
                    item.verification_message = "VERIFIED: Active endpoint check passed."
                    self.registry.register(item)
                    healthy_count += 1
                else:
                    item.consecutive_failures += 1
                    item.health_status = (
                        "unreachable" if item.consecutive_failures >= self.max_failures else "degraded"
                    )
                    item.verification_message = f"FAILED_PROBE ({item.consecutive_failures}/{self.max_failures}): {msg}"
                    if self.auto_clean and item.consecutive_failures >= self.max_failures:
                        self.registry.delete(item.id)
                        evicted_ids.append(item.id)
                        self.stats["resources_evicted"] += 1
                        await self.event_bus.publish(
                            "resource.evicted",
                            {"id": item.id, "consecutive_failures": item.consecutive_failures},
                        )
                    else:
                        self.registry.register(item)
                        degraded_count += 1

        await asyncio.gather(*(_check_item(i) for i in items))

        self.stats["sweeps_completed"] += 1
        self.stats["last_sweep_at"] = time.time()
        return {
            "checked": checked,
            "healthy": healthy_count,
            "degraded_or_unreachable": degraded_count,
            "evicted": evicted_ids,
            "auto_clean": self.auto_clean,
        }

    async def run_forever(self) -> None:
        """Background loop for the Ops Brain (runs embedded in combined mode or standalone in worker mode)."""
        self._running = True
        while self._running:
            try:
                await self.sweep_once()
            except Exception as exc:
                logger.debug("OpsBrain sweep error: %s", exc)
            await asyncio.sleep(self.sweep_interval_seconds)

    def start_background(self) -> Optional[asyncio.Task]:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop_background(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
