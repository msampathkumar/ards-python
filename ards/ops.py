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
from typing import Any, Dict, List, Optional, Set, Tuple
import httpx

from ards.config import ARDSConfig, settings
from ards.events import EventBus
from ards.models import ResourceRegistration, ResourceType
from ards.server.verifier import RegistrationVerifier, verifier as default_verifier

logger = logging.getLogger("ards.ops")


class ARDSOpsBrain:
    """
    Autonomous Operations Engine ("Brain of Ops") for ARDS.
    Responsibilities:
    1. Verify submitted registrations (in the background, or consumed via Pub/Sub queue).
    2. Periodically sweep and validate live endpoints in the registry.
    3. Evict non-working resources when `auto_clean=True` (`--auto-clean`).
    """

    def __init__(
        self,
        registry: Any,
        verifier: Optional[RegistrationVerifier] = None,
        event_bus: Optional[EventBus] = None,
        auto_clean: Optional[bool] = None,
        sweep_interval_seconds: Optional[float] = None,
        max_failures: Optional[int] = None,
        protect_seed_data: Optional[bool] = None,
        allow_local: Optional[bool] = None,
        probe_timeout_seconds: float = 3.0,
        max_concurrent_probes: int = 20,
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
        self.allow_local = allow_local if allow_local is not None else self.config.allow_local_endpoints
        self.probe_timeout_seconds = probe_timeout_seconds
        self.max_concurrent_probes = max_concurrent_probes

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._sweep_lock = asyncio.Lock()
        self._verification_tasks: Set[asyncio.Task] = set()
        self.stats: Dict[str, Any] = {
            "sweeps_completed": 0,
            "resources_verified": 0,
            "resources_evicted": 0,
            "last_sweep_at": None,
            "last_sweep_duration_ms": None,
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
        Used by the Frontend server on registration intake. Never blocks the caller on network probes:
        - Default simple mode: saves as `provisional` and verifies in a background task in this process.
        - Pub/Sub mode: saves as `provisional` and publishes `resource.submitted` for the Ops Brain worker.
        """
        res.health_status = "provisional"
        if not self.config.pubsub_enabled or self.event_bus.provider_name == "memory":
            res.verification_message = "Queued for background verification."
            saved = self.registry.register(res)
            self._schedule(self.verify_and_record(saved.model_copy()))
            return saved

        res.verification_message = "Queued for Ops Brain verification via Pub/Sub."
        saved = self.registry.register(res)
        await self.event_bus.publish("resource.submitted", saved.model_dump())
        return saved

    def _schedule(self, coro: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
            return
        self._verification_tasks.add(task)
        task.add_done_callback(self._verification_tasks.discard)

    async def wait_for_pending_verifications(self) -> None:
        """Waits for background verification tasks (useful in tests and graceful shutdown)."""
        if self._verification_tasks:
            await asyncio.gather(*list(self._verification_tasks), return_exceptions=True)

    async def probe_endpoint_live(self, res: ResourceRegistration) -> bool:
        """Actively checks whether a registered resource endpoint is reachable and healthy."""
        if res.type in (ResourceType.SKILL, ResourceType.PLUGIN):
            return True

        probe_url = res.endpoint
        if res.type == ResourceType.AGENT and res.schema_url:
            probe_url = res.schema_url

        try:
            async with httpx.AsyncClient(timeout=self.probe_timeout_seconds) as client:
                resp = await client.get(probe_url)
                return resp.status_code < 500
        except Exception:
            return False

    async def evaluate(self, res: ResourceRegistration) -> Tuple[bool, str]:
        """One health check = URL/SSRF policy check + a single live probe.

        Previously sweeps called the full verifier (which probes) AND probe_endpoint_live,
        doubling network calls per resource.
        """
        ok, msg = await self.verifier.check_url_policy(res, allow_local=self.allow_local)
        if not ok:
            return False, msg
        if await self.probe_endpoint_live(res):
            return True, "VERIFIED: Active endpoint check passed."
        return False, "UNREACHABLE: Endpoint did not respond (or returned 5xx)."

    async def _apply_result(
        self, item: ResourceRegistration, ok: bool, msg: str, auto_clean: Optional[bool] = None
    ) -> Optional[str]:
        """Updates health fields and evicts when needed. Returns the evicted id, if any."""
        clean = self.auto_clean if auto_clean is None else auto_clean
        item.last_verified_at = time.time()
        if ok:
            item.consecutive_failures = 0
            item.health_status = "healthy"
            item.verification_message = msg
            self.registry.register(item)
            return None

        item.consecutive_failures += 1
        item.health_status = "unreachable" if item.consecutive_failures >= self.max_failures else "degraded"
        item.verification_message = f"FAILED_CHECK ({item.consecutive_failures}/{self.max_failures}): {msg}"
        if clean and item.consecutive_failures >= self.max_failures:
            self.registry.delete(item.id)
            self.stats["resources_evicted"] += 1
            await self.event_bus.publish(
                "resource.evicted",
                {"id": item.id, "consecutive_failures": item.consecutive_failures, "reason": msg},
            )
            return item.id
        self.registry.register(item)
        return None

    async def verify_and_record(self, res: ResourceRegistration) -> ResourceRegistration:
        """Validates a resource and updates its status in the registry."""
        ok, msg = await self.evaluate(res)
        await self._apply_result(res, ok, msg)
        self.stats["resources_verified"] += 1
        await self.event_bus.publish("resource.verified", res.model_dump())
        return res

    async def sweep_once(self, auto_clean: Optional[bool] = None) -> Dict[str, Any]:
        """
        Runs a full validation pass over all registered resources (plus drains any pending Pub/Sub events).
        When `auto_clean=True` (`--auto-clean`), evicts resources that exceed `max_failures`.
        Sweeps never overlap: a manual `/api/v1/ops/sweep` waits for a running background sweep.
        `auto_clean` overrides the instance setting for this sweep only.
        """
        clean = self.auto_clean if auto_clean is None else auto_clean
        async with self._sweep_lock:
            started = time.perf_counter()
            sweep_started_at = time.time()
            await self.event_bus.poll_once()
            items = self.registry.list_all()
            sem = asyncio.Semaphore(self.max_concurrent_probes)

            checked = 0
            healthy_count = 0
            degraded_count = 0
            evicted_ids: List[str] = []

            async def _check_item(item: ResourceRegistration) -> None:
                nonlocal checked, healthy_count, degraded_count
                if self.protect_seed_data and item.metadata.get("seed") is True:
                    healthy_count += 1
                    return
                # Already checked moments ago while draining queued submissions above:
                # don't count a second failure for the same resource in one sweep.
                if item.last_verified_at is not None and item.last_verified_at >= sweep_started_at:
                    if item.health_status == "healthy":
                        healthy_count += 1
                    else:
                        degraded_count += 1
                    return

                async with sem:
                    checked += 1
                    ok, msg = await self.evaluate(item)
                    evicted = await self._apply_result(item, ok, msg, auto_clean=clean)
                    if ok:
                        healthy_count += 1
                    elif evicted:
                        evicted_ids.append(evicted)
                    else:
                        degraded_count += 1

            await asyncio.gather(*(_check_item(i) for i in items))

            self.stats["sweeps_completed"] += 1
            self.stats["last_sweep_at"] = time.time()
            self.stats["last_sweep_duration_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            return {
                "checked": checked,
                "healthy": healthy_count,
                "degraded_or_unreachable": degraded_count,
                "evicted": evicted_ids,
                "auto_clean": clean,
            }

    async def run_forever(self) -> None:
        """Background loop for the Ops Brain (runs embedded in combined mode or standalone in worker mode)."""
        self._running = True
        while self._running:
            try:
                await self.sweep_once()
            except Exception as exc:
                logger.warning("OpsBrain sweep error: %s", exc)
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
        for task in list(self._verification_tasks):
            task.cancel()
