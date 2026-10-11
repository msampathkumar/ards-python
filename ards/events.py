"""Event Bus & Pub/Sub Architecture for ARDS SDK.

- Default (`ARDS_PUBSUB_ENABLED=false`): Uses lightweight `InMemoryEventBus` inside the single process
  to power `@registry.on_registration` callbacks with zero setup.
- Optional Split Mode (`ARDS_PUBSUB_ENABLED=true`): Supports `SQLiteEventBus` (multi-process local queue)
  or `GCPPubSubEventBus` (`google-cloud-pubsub`) so the Frontend serving plane can publish registration
  requests and the standalone Ops Brain worker can consume, verify, and `--auto-clean` asynchronously.
"""

from abc import ABC, abstractmethod
import asyncio
import inspect
import json
import logging
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from ards.config import ARDSConfig, settings

logger = logging.getLogger("ards.events")

EventHandler = Callable[[str, Dict[str, Any]], Any]


class EventBus(ABC):
    """Unified Pub/Sub Event Bus Interface."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def subscribe(self, topic: str, handler: EventHandler) -> None:
        pass

    @abstractmethod
    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def publish_sync(self, topic: str, payload: Dict[str, Any]) -> None:
        pass

    async def poll_once(self, topic: str = "*") -> int:
        """Polls queued events (for pull-based buses like SQLiteEventBus / GCPPubSubEventBus)."""
        return 0


class InMemoryEventBus(EventBus):
    """Default zero-config in-process EventBus for single-process ARDS deployments."""

    def __init__(self):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        # Strong refs to fire-and-forget tasks; asyncio only keeps weak refs, so untracked tasks can vanish.
        self._pending_tasks: Set[asyncio.Task] = set()

    @property
    def provider_name(self) -> str:
        return "memory"

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        handlers = list(self._subscribers.get(topic, [])) + list(self._subscribers.get("*", []))
        for h in handlers:
            try:
                res = h(topic, payload)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.debug("EventBus handler error on %s: %s", topic, exc)

    def publish_sync(self, topic: str, payload: Dict[str, Any]) -> None:
        handlers = list(self._subscribers.get(topic, [])) + list(self._subscribers.get("*", []))
        for h in handlers:
            try:
                res = h(topic, payload)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(res)
                        self._pending_tasks.add(task)
                        task.add_done_callback(self._pending_tasks.discard)
                    except RuntimeError:
                        asyncio.run(res)
            except Exception as exc:
                logger.debug("EventBus sync handler error on %s: %s", topic, exc)


class SQLiteEventBus(EventBus):
    """
    Durable local multi-process Pub/Sub queue backed by SQLite WAL.
    Ideal for testing or running decoupled Frontend + Ops Brain worker processes on a single host.
    """

    def __init__(self, db_path: Optional[str] = None, retention_seconds: float = 86400.0):
        self.db_path = db_path or settings.pubsub_sqlite_path or "ards_events.db"
        self.retention_seconds = retention_seconds
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._shared_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def provider_name(self) -> str:
        return "sqlite-queue"

    def _get_conn(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_status ON event_queue(status, topic);")
            conn.commit()
            if self._shared_conn is None:
                conn.close()

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    def publish_sync(self, topic: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO event_queue (topic, payload_json, status, created_at) VALUES (?, ?, 'pending', ?);",
                (topic, json.dumps(payload), time.time()),
            )
            conn.commit()
            if self._shared_conn is None:
                conn.close()

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        self.publish_sync(topic, payload)

    async def poll_once(self, topic: str = "*") -> int:
        with self._lock:
            conn = self._get_conn()
            # BEGIN IMMEDIATE takes the write lock up front, so SELECT + UPDATE is one atomic claim.
            # Without it, two worker processes could read the same pending rows and process them twice.
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE;")
            try:
                if topic == "*":
                    rows = conn.execute(
                        "SELECT * FROM event_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 50;"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM event_queue WHERE status = 'pending' AND topic = ? ORDER BY id ASC LIMIT 50;",
                        (topic,),
                    ).fetchall()

                ids = [r["id"] for r in rows]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    conn.execute(
                        f"UPDATE event_queue SET status = 'processed' WHERE id IN ({placeholders});",
                        ids,
                    )
                # Retention: drop processed events older than the retention window.
                conn.execute(
                    "DELETE FROM event_queue WHERE status = 'processed' AND created_at < ?;",
                    (time.time() - self.retention_seconds,),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
            finally:
                conn.isolation_level = ""
                if self._shared_conn is None:
                    conn.close()

        processed = 0
        for row in rows:
            ev_topic = row["topic"]
            payload = json.loads(row["payload_json"])
            handlers = list(self._subscribers.get(ev_topic, [])) + list(self._subscribers.get("*", []))
            for h in handlers:
                try:
                    res = h(ev_topic, payload)
                    if inspect.isawaitable(res):
                        await res
                except Exception as exc:
                    logger.debug("SQLiteEventBus handler error: %s", exc)
            processed += 1
        return processed


class GCPPubSubEventBus(EventBus):
    """
    Production Google Cloud Pub/Sub EventBus for high-scale decoupled ARDS deployments.
    Falls back gracefully to InMemoryEventBus if `google-cloud-pubsub` or credentials are absent.
    """

    def __init__(
        self,
        project: Optional[str] = None,
        topic_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        publisher_client: Optional[object] = None,
        subscriber_client: Optional[object] = None,
    ):
        self.project = project or settings.google_cloud_project
        self.topic_id = topic_id or settings.gcp_pubsub_topic
        self.subscription_id = subscription_id or settings.gcp_pubsub_subscription
        self._fallback = InMemoryEventBus()
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._publisher = publisher_client
        self._subscriber = subscriber_client
        self._gcp_ready = False
        self._init_gcp()

    @property
    def provider_name(self) -> str:
        return "gcp-pubsub" if self._gcp_ready else "gcp-pubsub-fallback"

    def _init_gcp(self) -> None:
        if self._publisher is not None:
            self._gcp_ready = True
            return
        if not self.project:
            return
        try:
            from google.cloud import pubsub_v1  # type: ignore

            self._publisher = pubsub_v1.PublisherClient()
            self._subscriber = pubsub_v1.SubscriberClient()
            self._gcp_ready = True
        except Exception as exc:
            logger.warning("Google Cloud Pub/Sub unavailable (%s); falling back to memory bus.", exc)
            self._gcp_ready = False

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(topic, []).append(handler)
        self._fallback.subscribe(topic, handler)

    def publish_sync(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._gcp_ready and self._publisher is not None:
            try:
                topic_path = f"projects/{self.project}/topics/{self.topic_id}"
                envelope = json.dumps({"topic": topic, "payload": payload}).encode("utf-8")
                self._publisher.publish(topic_path, data=envelope, event_topic=topic)
                return
            except Exception as exc:
                logger.debug("GCP Pub/Sub publish failed (%s); using fallback.", exc)
        self._fallback.publish_sync(topic, payload)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._gcp_ready and self._publisher is not None:
            await asyncio.to_thread(self.publish_sync, topic, payload)
            return
        await self._fallback.publish(topic, payload)

    async def poll_once(self, topic: str = "*") -> int:
        if not self._gcp_ready or self._subscriber is None:
            return 0
        sub_path = f"projects/{self.project}/subscriptions/{self.subscription_id}"
        try:
            response = await asyncio.to_thread(
                self._subscriber.pull,
                request={"subscription": sub_path, "max_messages": 25},
            )
            ack_ids = []
            count = 0
            for received in getattr(response, "received_messages", []):
                ack_ids.append(received.ack_id)
                data = json.loads(received.message.data.decode("utf-8"))
                ev_topic = data.get("topic", "resource.submitted")
                payload = data.get("payload", {})
                handlers = list(self._subscribers.get(ev_topic, [])) + list(self._subscribers.get("*", []))
                for h in handlers:
                    res = h(ev_topic, payload)
                    if inspect.isawaitable(res):
                        await res
                count += 1
            if ack_ids:
                await asyncio.to_thread(
                    self._subscriber.acknowledge,
                    request={"subscription": sub_path, "ack_ids": ack_ids},
                )
            return count
        except Exception as exc:
            logger.debug("GCP Pub/Sub pull skipped: %s", exc)
            return 0


def create_event_bus(cfg: Optional[ARDSConfig] = None) -> EventBus:
    """Builds the configured EventBus. Defaults to InMemoryEventBus unless ARDS_PUBSUB_ENABLED=true."""
    c = cfg or settings
    if not c.pubsub_enabled:
        return InMemoryEventBus()
    provider = (c.pubsub_provider or "memory").lower()
    if provider == "sqlite":
        return SQLiteEventBus(db_path=c.pubsub_sqlite_path)
    if provider == "gcp":
        return GCPPubSubEventBus(
            project=c.google_cloud_project,
            topic_id=c.gcp_pubsub_topic,
            subscription_id=c.gcp_pubsub_subscription,
        )
    return InMemoryEventBus()
