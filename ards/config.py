"""ARDS Configuration Loader (.env and Environment Variable Support)."""

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional


def _parse_bool(val: Optional[str], default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_dotenv(env_path: Optional[str] = None, override: bool = False) -> dict:
    """Lightweight, zero-dependency .env parser that loads variables into os.environ."""
    loaded = {}
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    else:
        candidates.append(Path.cwd() / ".env")
        candidates.append(Path(__file__).resolve().parent.parent / ".env")

    for path in candidates:
        if path.is_file():
            try:
                for raw_line in path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Strip inline comments if unquoted
                    if value and value[0] not in ('"', "'") and " #" in value:
                        value = value.split(" #", 1)[0].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    loaded[key] = value
                    if override or key not in os.environ:
                        os.environ[key] = value
            except OSError:
                pass
            break
    return loaded


@dataclass
class ARDSConfig:
    """Centralized SDK and Server configuration loaded from .env or environment variables."""

    project_dir: str = "."
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # Storage & Search Backend: sqlite (default) | bigquery | vertex | hybrid
    backend: str = "sqlite"
    sqlite_path: str = "ards_registry.db"
    seed_defaults: bool = True

    # Ops Brain & Auto-Clean
    mode: str = "combined"  # combined | frontend | worker
    auto_clean: bool = False
    sweep_interval_seconds: float = 60.0
    max_failures: int = 3
    protect_seed_data: bool = True

    # Optional Production Pub/Sub (Disabled by default)
    pubsub_enabled: bool = False
    pubsub_provider: str = "memory"  # memory | sqlite | gcp
    pubsub_sqlite_path: str = "ards_events.db"
    gcp_pubsub_topic: str = "ards-registrations"
    gcp_pubsub_subscription: str = "ards-ops-brain-sub"

    # Optional Google Cloud BigQuery & Vertex AI Search
    google_cloud_project: Optional[str] = None
    bq_dataset: str = "ards_registry"
    bq_table: str = "resources"
    bq_audit_table: str = "registrations_log"
    bq_cache_ttl_seconds: float = 30.0
    vertex_search_datastore_id: Optional[str] = None
    vertex_search_location: str = "global"

    # Security
    # admin_token: when set, admin actions (DELETE, ops sweep, endpoint takeover) need
    # `Authorization: Bearer <token>`. When unset, admin actions are allowed only from loopback clients.
    admin_token: Optional[str] = None
    # allow_local_endpoints: accept localhost/private-IP endpoints (handy for local dev; set false when hosted).
    allow_local_endpoints: bool = True

    @classmethod
    def from_env(cls, env_file: Optional[str] = None, override_env: bool = False) -> "ARDSConfig":
        load_dotenv(env_file, override=override_env)
        project_dir = os.environ.get("ARDS_PROJECT_DIR", ".")
        raw_sqlite = os.environ.get("ARDS_SQLITE_PATH", "ards_registry.db")
        if raw_sqlite != ":memory:" and not os.path.isabs(raw_sqlite) and project_dir != ".":
            sqlite_path = str(Path(project_dir) / raw_sqlite)
        else:
            sqlite_path = raw_sqlite

        raw_pubsub_sqlite = os.environ.get("ARDS_PUBSUB_SQLITE_PATH", "ards_events.db")
        if raw_pubsub_sqlite != ":memory:" and not os.path.isabs(raw_pubsub_sqlite) and project_dir != ".":
            pubsub_sqlite_path = str(Path(project_dir) / raw_pubsub_sqlite)
        else:
            pubsub_sqlite_path = raw_pubsub_sqlite

        gcp_proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or None
        vertex_ds = os.environ.get("VERTEX_SEARCH_DATASTORE_ID", "").strip() or None

        return cls(
            project_dir=project_dir,
            host=os.environ.get("ARDS_HOST", "127.0.0.1"),
            port=int(os.environ.get("ARDS_PORT", "8000")),
            reload=_parse_bool(os.environ.get("ARDS_RELOAD"), default=False),
            backend=os.environ.get("ARDS_BACKEND", "sqlite").strip().lower(),
            sqlite_path=sqlite_path,
            seed_defaults=_parse_bool(os.environ.get("ARDS_SEED_DEFAULTS"), default=True),
            mode=os.environ.get("ARDS_MODE", "combined").strip().lower(),
            auto_clean=_parse_bool(os.environ.get("ARDS_AUTO_CLEAN"), default=False),
            sweep_interval_seconds=float(os.environ.get("ARDS_SWEEP_INTERVAL_SECONDS", "60")),
            max_failures=int(os.environ.get("ARDS_MAX_FAILURES", "3")),
            protect_seed_data=_parse_bool(os.environ.get("ARDS_PROTECT_SEED_DATA"), default=True),
            pubsub_enabled=_parse_bool(os.environ.get("ARDS_PUBSUB_ENABLED"), default=False),
            pubsub_provider=os.environ.get("ARDS_PUBSUB_PROVIDER", "memory").strip().lower(),
            pubsub_sqlite_path=pubsub_sqlite_path,
            gcp_pubsub_topic=os.environ.get("ARDS_GCP_PUBSUB_TOPIC", "ards-registrations"),
            gcp_pubsub_subscription=os.environ.get("ARDS_GCP_PUBSUB_SUBSCRIPTION", "ards-ops-brain-sub"),
            google_cloud_project=gcp_proj,
            bq_dataset=os.environ.get("ARDS_BQ_DATASET", "ards_registry"),
            bq_table=os.environ.get("ARDS_BQ_TABLE", "resources"),
            bq_audit_table=os.environ.get("ARDS_BQ_AUDIT_TABLE", "registrations_log"),
            bq_cache_ttl_seconds=float(os.environ.get("ARDS_BQ_CACHE_TTL_SECONDS", "30")),
            vertex_search_datastore_id=vertex_ds,
            vertex_search_location=os.environ.get("VERTEX_SEARCH_LOCATION", "global"),
            admin_token=os.environ.get("ARDS_ADMIN_TOKEN", "").strip() or None,
            allow_local_endpoints=_parse_bool(os.environ.get("ARDS_ALLOW_LOCAL_ENDPOINTS"), default=True),
        )


settings = ARDSConfig.from_env()


def reload_settings(env_file: Optional[str] = None, override_env: bool = False) -> ARDSConfig:
    """Re-read .env / environment and update the shared `settings` object in place.

    Modules hold a reference to the same `settings` object, so in-place updates reach all of them.
    The CLI calls this after applying flags like `--backend` and `--auto-clean`.
    """
    fresh = ARDSConfig.from_env(env_file, override_env=override_env)
    for f in fields(fresh):
        setattr(settings, f.name, getattr(fresh, f.name))
    return settings
