"""CLI Entrypoint for ARDS SDK & Server (`python -m ards.cli` or `ards`).

Supports:
1. Default simple single-process mode:
   `python -m ards.cli serve [--port 8000] [--auto-clean]`
2. Split Frontend-only mode (with optional Pub/Sub):
   `python -m ards.cli serve --mode frontend`
3. Standalone Ops Brain worker mode (consumes Pub/Sub, validates endpoints, and evicts dead ones with `--auto-clean`):
   `python -m ards.cli ops-worker --auto-clean`
"""

import argparse
import asyncio
import os
import uvicorn

from ards.config import ARDSConfig, load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ards",
        description="ARDS Python SDK & Discovery Server CLI",
    )
    parser.add_argument("--env-file", default=None, help="Path to optional .env file")
    subparsers = parser.add_subparsers(dest="command")

    # 1. `serve` command
    serve_parser = subparsers.add_parser("serve", help="Run the ARDS Discovery Server")
    serve_parser.add_argument("--host", default=None, help="Bind host (default from .env or 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=None, help="Bind port (default from .env or 8000)")
    serve_parser.add_argument(
        "--backend",
        choices=["sqlite", "bigquery", "vertex", "hybrid"],
        default=None,
        help="Storage & search backend (default: sqlite)",
    )
    serve_parser.add_argument(
        "--mode",
        choices=["combined", "frontend"],
        default=None,
        help="Serving mode: 'combined' (default, includes Ops Brain) or 'frontend' (serving only)",
    )
    serve_parser.add_argument(
        "--auto-clean",
        action="store_true",
        help="Automatically evict unreachable/non-working resources during Ops Brain sweeps",
    )
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    # 2. `ops-worker` command
    worker_parser = subparsers.add_parser(
        "ops-worker",
        help="Run the standalone ARDS Ops Brain verification & cleanup worker",
    )
    worker_parser.add_argument(
        "--auto-clean",
        action="store_true",
        help="Automatically evict unreachable/non-working resources",
    )
    worker_parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Sweep interval in seconds (default: 60)",
    )
    worker_parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single verification & cleanup sweep and exit",
    )

    args = parser.parse_args()
    load_dotenv(args.env_file)

    if getattr(args, "backend", None):
        os.environ["ARDS_BACKEND"] = args.backend
    if getattr(args, "mode", None):
        os.environ["ARDS_MODE"] = args.mode
    if getattr(args, "auto_clean", False):
        os.environ["ARDS_AUTO_CLEAN"] = "true"
    if getattr(args, "interval", None) is not None:
        os.environ["ARDS_SWEEP_INTERVAL_SECONDS"] = str(args.interval)

    cfg = ARDSConfig.from_env(args.env_file, override_env=False)

    if args.command == "ops-worker":
        from ards.ops import ARDSOpsBrain
        from ards.registry import Registry

        reg = Registry(config=cfg)
        brain = ARDSOpsBrain(registry=reg, auto_clean=cfg.auto_clean, config=cfg)
        if args.once:
            summary = asyncio.run(brain.sweep_once())
            print(f"ARDS Ops Brain sweep complete: {summary}")
        else:
            print(
                f"Starting ARDS Ops Brain Worker (backend={reg.backend.backend_name}, "
                f"bus={reg.event_bus.provider_name}, auto_clean={brain.auto_clean})..."
            )
            asyncio.run(brain.run_forever())
        return

    # Default to `serve`
    host = getattr(args, "host", None) or cfg.host
    port = getattr(args, "port", None) or cfg.port
    reload_flag = getattr(args, "reload", False) or cfg.reload
    uvicorn.run("ards.server.app:app", host=host, port=port, reload=reload_flag)


if __name__ == "__main__":
    main()
