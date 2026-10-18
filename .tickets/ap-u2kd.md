---
id: ap-u2kd
status: open
deps: [ap-ox99]
links: []
created: 2026-10-18T00:19:22Z
type: feature
priority: 2
assignee: Sampath Kumar
parent: ap-rl34
---
# P0-4 Async SDK: heartbeat loop, context-managed registration, capability-scoped search in ARDSClient

## Acceptance Criteria

async with ARDSClient.registered(resource) registers on enter, deregisters on exit; heartbeat loop cancellable; tests use ASGITransport against ards.server.app (no real network).

