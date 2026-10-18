# Standard: Security Rules (ards-python)

ARDS fetches URLs that strangers submit (AgentCard probes, MCP probes,
introspection). These rules exist to stop server-side request forgery (SSRF)
and secret leaks. Code that fetches a submitted URL must satisfy all of them.

## Current state (verified by reading code on 2026-10-18)

- `ards/server/verifier.py` `RegistrationVerifier.verify(..., allow_local=True)`:
  the private-range check runs only when `allow_local` is `False`.
- `ards/server/app.py` (`POST /api/v1/resources`) and
  `ards/server/registration_ui.py` call `verify()` without `allow_local`, so
  the private-range check is **off** on both public paths.
- The check is a regex on the hostname string: no DNS resolution, no IPv6,
  no `0.0.0.0`, and redirects are not re-checked.
- Tracked as ticket `ap-12in` (tag `needs-owner`: default-deny vs demo mode).

## Rules for any outbound fetch of a user-supplied URL

1. Scheme must be `http` or `https`.
2. Resolve the hostname and reject if **any** resolved address is loopback,
   private, link-local, multicast, reserved, or unspecified
   (`ipaddress.ip_address(x).is_global` must be `True`), for IPv4 and IPv6.
3. Disable automatic redirects, or re-apply rule 2 to every redirect target.
4. Timeout ≤ 5 seconds; response body read capped (target ≤ 1 MB — UNVERIFIED
   value, owner to confirm).
5. Local/private targets allowed only when an explicit opt-in is set
   (proposed: `ARDS_ALLOW_LOCAL=1`; UNVERIFIED until `ap-12in` is decided).
6. Tests for fetch code use `httpx.MockTransport` and include at least one
   rejected private target (`127.0.0.1`, `169.254.169.254`, `[::1]`).

## Secrets

- Never commit credentials, `.env`, service-account JSON, or tokens;
  `scripts/validate_change.py` blocks common key patterns.
- Cloud project IDs and data-store IDs come from env vars; hard-coded
  defaults must be obvious placeholders.

## Reporting

Security findings get a tk ticket with type `bug`, priority `0`, tag
`security`; never describe an exploit path in public commit messages beyond
the file and rule violated.
