# Standard: Engineering Rules (ards-python)

Single source of truth for code, test, and commit rules. Enforced by
`scripts/validate_change.py`, which reads the fenced blocks below — edit the
patterns here, never in the script.

## Stack (verified from `pyproject.toml` on 2026-10-18)

- Python `>=3.10`; package `ards` (setuptools); runtime deps: fastapi,
  uvicorn, pydantic v2, httpx, jinja2, python-multipart.
- Dev deps: `pytest`, `pytest-asyncio` → install with `pip install -e ".[dev]"`
  inside `.venv/`.
- Run the server: `python -m uvicorn ards.server.app:app --port 8000`.

## Layout

| Concern | Path |
| :--- | :--- |
| Data models (pydantic) | `ards/models.py` |
| Registry / search logic | `ards/registry.py` |
| HTTP API + HTML UI | `ards/server/app.py`, `ards/server/registration_ui.py` |
| A2A / MCP endpoints | `ards/server/interfaces.py` |
| Registration verification (SSRF) | `ards/server/verifier.py` — rules in `standards/security.md` |
| Plugins | `ards/plugins/base.py` (interface), `ards/plugins/<vendor>_plugins.py` |
| Client SDK | `ards/client/client.py` |
| Tests | `tests/test_<area>.py` |

New modules go in the row whose concern matches; do not create new top-level
packages without a ticket that says so.

## Code rules

1. Public REST endpoints live under `/api/v1/`; each new endpoint has a
   `response_model` and at least one test hitting it via `ASGITransport`.
2. Every public function/class added has a one-line docstring.
3. Plugin hooks stay fault-isolated (a plugin error never fails a request),
   but errors are **logged** through the module logger
   (`logger = logging.getLogger(__name__)`): `logger.exception(...)` for
   unexpected errors, `logger.info(..., exc_info=True)` for expected probe
   failures. Never silently swallowed.
4. No module-level network calls; no network at import time.
5. Configuration comes from environment variables named `ARDS_<NAME>` with
   a safe default documented in the README.
6. Cloud SDK calls (BigQuery, Vertex AI) stay behind a plugin and are
   skipped when credentials are absent; tests never call cloud services.

## Test rules

1. Tests make **no real network calls**: HTTP to the app uses
   `httpx.ASGITransport(app=app)`; outbound HTTP uses `httpx.MockTransport`.
2. No `time.sleep` in tests; inject a clock instead.
3. Any change under `ards/` comes with at least one added or changed
   `tests/test_*.py` in the same change.
4. Async tests use `@pytest.mark.asyncio`.
5. Golden example: `tests/test_full_suite.py`; template: `templates/test_module.py.tmpl`.

## Forbidden in added lines of `ards/**/*.py` (regex, one per line)

```forbidden-code
^\s*print\(
breakpoint\(
pdb\.set_trace\(
verify\s*=\s*False
^\s*except\s*:
```

## Forbidden in added lines of any file (secrets; regex)

```forbidden-secrets
AIza[0-9A-Za-z_\-]{35}
-----BEGIN [A-Z ]*PRIVATE KEY-----
sk-[A-Za-z0-9]{20,}
"private_key_id"\s*:
```

## Forbidden in added lines of `tests/**/*.py` (network; regex)

```forbidden-tests
time\.sleep\(
requests\.(get|post|put|delete)\(
httpx\.(get|post|put|delete)\(
```

## Swallowed exceptions

`scripts/validate_change.py` also flags `except ...:` followed directly by
`pass` in every **changed** `ards/` file (whole file). Touching a file
obliges you to replace those with a logged handler (code rule 3).

## Commits

- Conventional commits: `<type>(<scope>): <summary> (<ticket-id>)`, types
  `feat|fix|docs|test|refactor|chore`.
- One concern per commit; `git add <explicit paths>` only; include `.tickets/`.
