# AGENTS.md — ards-python

Instructions for coding agents (and humans) changing this repository.

## Mission
ARDS is a Python SDK and FastAPI server that registers, indexes, and lets
agents discover A2A agents, MCP servers, skills, and plugins at runtime.
This repo is the open-source core (Apache-2.0).

**Audience:** developers building multi-agent systems who need runtime
discovery instead of hard-coded peer URLs.

## Milestone P0 — Core Foundation (numeric DoD)
Source: `docs/research/ards_product_and_engineering_blueprint.md` §4.2.
tk epic: `ap-rl34`.

| # | Ticket | Item |
| :--- | :--- | :--- |
| P0-1 | `ap-8yho` | Storage backend interface + in-memory and SQLite implementations |
| P0-2 | `ap-ox99` | Heartbeat & TTL lease endpoints, degradation and reaping |
| P0-3 | `ap-z1ot` | Background introspection of AgentCards / MCP tool schemas |
| P0-4 | `ap-u2kd` | Async SDK: heartbeat loop, context-managed registration |

**Done when:** 4/4 tickets closed (`python3 scripts/next_item.py --epic ap-rl34`
prints `NONE` and reports `progress: 4/4 closed`) **and**
`python3 scripts/validate_change.py --all` reports no `pytest`/`compile`
violations on `master`.

## Workflow index
| Trigger | Workflow file |
| :--- | :--- |
| Implement the next roadmap item, feature, or bug fix | `workflows/implement-ticket.md` |
| Write a new ticket | `templates/feature-ticket.md` |

One run = one ticket. Pick it with `python3 scripts/next_item.py --epic ap-rl34`;
never choose by judgement.

## Where things live
| What | Path |
| :--- | :--- |
| Code, test, commit rules; forbidden patterns | `standards/engineering.md` |
| SSRF / secret rules for URL fetching | `standards/security.md` |
| Test template / golden test | `templates/test_module.py.tmpl` / `tests/test_full_suite.py` |
| Gate (compile, pytest, tests-with-code, patterns) | `scripts/validate_change.py` |
| Next ticket | `scripts/next_item.py` |
| Product & architecture background | `docs/research/ards_product_and_engineering_blueprint.md` |
| Task tracking | `.tickets/` (tk, committed) |

## Quick commands
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
python3 scripts/validate_change.py          # before every commit
```

## Automation boundary
- No automation targets this repo as of 2026-10-18.
- If one is added, its prompt must name `workflows/implement-ticket.md`, run
  1 ticket per invocation, and **pause** when `next_item.py --epic ap-rl34`
  prints `NONE` (4/4 closed or only `needs-owner` tickets left) or any ticket
  note contains `BLOCKED`.
- Tickets tagged `needs-owner` (e.g. `ap-12in`, security default) are never
  worked by automation.

## Red lines (each testable)
- Never commit when `python3 scripts/validate_change.py` exits non-zero.
- Never change code under `ards/` without a changed `tests/test_*.py`
  (validator check 3).
- Never make real network or cloud calls in tests (validator patterns;
  `standards/engineering.md` test rules).
- Never fetch a user-supplied URL without the checks in `standards/security.md`.
- Never commit secrets, `.env`, or service-account files (validator patterns).
- Never publish to PyPI, deploy, or push tags from a workflow; releases are
  an owner action.
- Always `git add <explicit paths>` (never `git add .` / `-A`) and include
  `.tickets/` in the commit.
- Max 2 fix loops per gate; then `BLOCKED` note + `needs-owner` tag, STOP.
