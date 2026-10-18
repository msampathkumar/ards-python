---
id: ap-z1ot
status: open
deps: [ap-8yho]
links: []
created: 2026-10-18T00:19:22Z
type: feature
priority: 2
assignee: Sampath Kumar
parent: ap-rl34
---
# P0-3 Introspection worker: parse .well-known/agent.json and MCP tool schemas after registration

## Acceptance Criteria

Runs as background task after registration; HTTP mocked in tests with httpx.MockTransport; failures set health_status and never raise into the request; respects SSRF rules in standards/security.md.

