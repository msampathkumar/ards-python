---
id: ap-8yho
status: open
deps: []
links: []
created: 2026-10-18T00:19:22Z
type: feature
priority: 1
assignee: Sampath Kumar
parent: ap-rl34
---
# P0-1 Storage decoupling: abstract storage backend with in-memory and SQLite (JSON) implementations

## Acceptance Criteria

Registry uses a StorageBackend interface; InMemoryBackend and SQLiteBackend both pass the same parametrized pytest suite; SQLite file path configurable via ARDS_DB_PATH; no network in tests.

