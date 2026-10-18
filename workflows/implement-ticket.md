# Workflow: implement ticket

**Produces:** one closed tk ticket = code under `ards/` + tests under `tests/test_<area>.py` + ticket notes   **Runs per invocation:** 1 ticket
**Skill(s):** none   **Standards:** `standards/engineering.md`, `standards/security.md`
**Templates:** `templates/test_module.py.tmpl`, `templates/feature-ticket.md`   **Golden example:** `tests/test_full_suite.py`

## Preconditions
- [ ] `git status --porcelain` prints nothing and `git pull --rebase` succeeded.
- [ ] Environment: `.venv/bin/python -m pytest --version` works; if not, `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- [ ] Baseline green: `python3 scripts/validate_change.py` exits 0. If not, STOP and open a `bug` ticket with the output.

## Inputs
| Input | Path / Command |
| :--- | :--- |
| Next ticket | `python3 scripts/next_item.py --epic ap-rl34` → `<id>  <priority>  <title>` |
| Acceptance criteria | `tk show <id>` |
| Design reference | `docs/research/ards_product_and_engineering_blueprint.md` §4.2 (P0 items) and §5 (schemas) |
| Where code goes | Layout table in `standards/engineering.md` |

## Steps
1. **Select unit.** `python3 scripts/next_item.py --epic ap-rl34`. `NONE` → milestone P0 reached (or blocked on a `needs-owner` ticket): STOP.
2. **Ticket.** `tk start <id>` (the ticket already exists; never create a duplicate).
3. **Read context.** `tk show <id>`, the blueprint section it names, the files in the Layout rows it touches, `standards/engineering.md`, and `standards/security.md` if the change fetches any URL. Nothing else is required.
4. **Write failing tests first.** Copy `templates/test_module.py.tmpl` to `tests/test_<area>.py` (or extend an existing test file for that area). One test per acceptance criterion. Run `.venv/bin/python -m pytest -q tests/test_<area>.py` and confirm the new tests fail.
5. **Implement** the smallest code that makes those tests pass, in the files named by the Layout table.
6. **Validate (Layer A).** `tk add-note <id> "progress: <what changed>"` (so `.tickets/` is in the diff), then `python3 scripts/validate_change.py`; fix until exit 0 (max 2 fix loops).
7. **Rubric (Layer B).** Answer every question below YES/NO with a file:line or test name as evidence.
8. **Record.** `tk add-note <id> "validate_change PASS (<pytest summary line>); rubric 8/8; files: <list>"`; `tk close <id>`.
9. **Commit.** `git add <each changed file> .tickets/ && git commit -m "feat(<scope>): <summary> (<id>)"` (use `fix` for bugs); `git pull --rebase && git push`.

## Rubric (all must be YES)
1. Does every acceptance criterion in `tk show <id>` map to a named test?
2. Did those tests fail before step 5 and pass after?
3. Do tests avoid real network and `sleep` (ASGITransport / MockTransport / injected clock)?
4. Does each new `/api/v1/` endpoint declare a `response_model`?
5. Is every new public function/class documented with a one-line docstring?
6. If code fetches a submitted URL, does it meet `standards/security.md` rules 1–6, with a test rejecting a private target?
7. Is new configuration read from an `ARDS_<NAME>` env var with its default documented in README.md?
8. Is the change limited to this ticket (no unrelated refactors or files)?

## Failure handling
- `tests: ards/ changed but no tests/test_*.py changed` → add the test from step 4; never weaken the gate.
- `swallowed-exception` in a file you touched → replace `pass` with `logging.getLogger(__name__).exception("<context>")`.
- Dependency ticket still open (`next_item` skipped it) → do not work around it; pick what `next_item` prints.
- Ticket needs a product or security decision → `tk update <id> --tags needs-owner` (append to existing tags), `tk status <id> open`, `tk add-note <id> "BLOCKED: needs owner: <question>"`, STOP.
- Still failing after 2 fix loops → `tk add-note <id> "BLOCKED: <validator lines>"`, `tk update <id> --tags needs-owner` (append to existing tags), `tk status <id> open`, commit only `.tickets/`, do not commit code (`git stash` it), STOP.

## Definition of Done
- `python3 scripts/validate_change.py` exit 0, rubric 8/8 YES, ticket closed, commit pushed, `next_item.py` advances.
