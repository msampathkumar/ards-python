---
id: ap-re4k
status: closed
deps: []
links: []
created: 2026-10-18T00:19:22Z
type: task
priority: 1
assignee: Sampath Kumar
---
# Model-proof: AGENTS.md, engineering/security standards, implement-ticket workflow, validator


## Notes

**2026-10-18T00:22:32Z**

Added AGENTS.md (P0 milestone with numeric DoD 4/4 tickets + validator, workflow index, automation boundary, testable red lines), standards/engineering.md + standards/security.md (patterns read by validator), workflows/implement-ticket.md, templates/test_module.py.tmpl + templates/feature-ticket.md (golden: tests/test_full_suite.py, .tickets/ap-ox99.md), scripts/validate_change.py (compile, pytest, tests-with-code, ticket trail, forbidden code/secret/test-network patterns, swallowed exceptions) and scripts/next_item.py (tk-based, deterministic). Created epic ap-rl34 + P0-1..4 (ap-8yho, ap-ox99, ap-z1ot, ap-u2kd with deps) and security ticket ap-12in (needs-owner). Validator negative test (print + fake key, no test) -> 3 violations as expected. Existing code audit: 4 swallowed exceptions -> fixed in ap-vzxx; --all now PASS. Checklist before 0/12 (no AGENTS.md, no workflows; only .tickets committed, no epic) -> after 11/12 (#11 N/A: no automation targets repo). Note: repo is public; AGENTS.md kept engineering-only, no internal persona/portfolio content.
