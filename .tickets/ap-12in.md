---
tags: [security, needs-owner]
id: ap-12in
status: closed
deps: []
links: []
created: 2026-10-18T00:19:22Z
type: bug
priority: 0
assignee: Sampath Kumar
---
# SECURITY: SSRF check disabled on public registration paths (allow_local defaults to True)

Private-range (SSRF) check in ards/server/verifier.py is not enforced on the public registration paths (app.py POST /api/v1/resources, registration_ui.py), and the hostname check does not cover DNS resolution, IPv6, or redirects. Fix per standards/security.md rules 1-6. Owner decision needed: default-deny with an explicit opt-in for local demos (proposed ARDS_ALLOW_LOCAL=1)?


## Notes

**2026-10-22T00:16:39Z**

Owner decision 2026-10-22: Default deny with strict SSRF validation for internal, link-local, loopback, metadata, and unresolvable IPs. Allow local demos only with explicit ARDS_ALLOW_LOCAL=1 opt-in. Added unit tests for loopback and metadata rejection.
