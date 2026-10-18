# Template: feature / bug ticket

Create with:

```bash
tk create "{{P0-N or area}}: {{one-line outcome}}" -t {{feature|bug}} -p {{0-3}} \
  --parent {{epic-id}} \
  --acceptance "{{criterion 1}}; {{criterion 2}}; {{criterion 3}}"
```

Rules for acceptance criteria (each must be checkable by a test or command):

- Name the exact endpoint, class, or function (`POST /api/v1/heartbeat`, `ARDSClient.registered`).
- State the observable result with a value (`status 200`, `health_status == "degraded"`).
- Say how time and network are faked in tests (`injectable clock`, `httpx.MockTransport`).
- 2–5 criteria. If you need more, split the ticket.

Golden example: `.tickets/ap-ox99.md` (P0-2 heartbeat & lease).
