---
id: ap-ox99
status: open
deps: [ap-8yho]
links: []
created: 2026-10-18T00:19:22Z
type: feature
priority: 1
assignee: Sampath Kumar
parent: ap-rl34
---
# P0-2 Heartbeat & lease: POST /api/v1/heartbeat and GET /api/v1/resources/{id}/health with TTL degradation and reaping

## Acceptance Criteria

TTL configurable; resource without heartbeat for >TTL becomes degraded, >2xTTL unreachable, >3xTTL removed; time is injectable in tests (no sleep); tests cover all 3 transitions.

