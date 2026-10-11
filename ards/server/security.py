"""Shared security helpers for the ARDS server: admin auth, takeover protection, and HTTP headers."""

import ipaddress
import logging
import secrets
from typing import Optional

from fastapi import HTTPException, Request

from ards.config import settings
from ards.models import ResourceRegistration

logger = logging.getLogger("ards.security")

# CSP for the HTML pages we render. The UI loads Tailwind (script) and Google Fonts (styles/fonts) from CDNs.
# TODO(security): self-host Tailwind and fonts to drop the CDN allowances and 'unsafe-inline' styles.
HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _is_loopback_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_admin(request: Request) -> bool:
    """Admin if a valid `Authorization: Bearer <ARDS_ADMIN_TOKEN>` is sent.

    With no ARDS_ADMIN_TOKEN configured, only loopback clients (same machine) count as admin,
    which keeps local development friction-free while protecting hosted deployments by default.
    """
    token = settings.admin_token
    if token:
        auth = request.headers.get("authorization", "")
        scheme, _, presented = auth.partition(" ")
        return scheme.lower() == "bearer" and secrets.compare_digest(presented.strip(), token)
    return _is_loopback_client(request)


def require_admin(request: Request) -> None:
    """FastAPI dependency for destructive/admin endpoints."""
    if not is_admin(request):
        raise HTTPException(
            status_code=401,
            detail="Admin access required. Send 'Authorization: Bearer <ARDS_ADMIN_TOKEN>'.",
        )


def takeover_error(existing: Optional[ResourceRegistration], incoming: ResourceRegistration, request: Request) -> Optional[str]:
    """Blocks re-registering an existing id with a different endpoint/schema_url, unless admin.

    Same-endpoint re-registration (e.g. an agent refreshing its metadata on restart) is still allowed.
    Without this check anyone could point a trusted agent id at their own server.
    """
    if existing is None:
        return None
    changed = existing.endpoint != incoming.endpoint or (existing.schema_url or None) != (incoming.schema_url or None)
    if changed and not is_admin(request):
        return (
            f"ID_CONFLICT: '{incoming.id}' is already registered with a different endpoint. "
            "Use a new id, or ask an admin to update it."
        )
    return None


def warn_if_exposed_without_token(host: str) -> None:
    if host not in ("127.0.0.1", "localhost", "::1") and not settings.admin_token:
        logger.warning(
            "ARDS is listening on %s without ARDS_ADMIN_TOKEN. Admin endpoints are limited to loopback "
            "clients; set ARDS_ADMIN_TOKEN (and ARDS_ALLOW_LOCAL_ENDPOINTS=false) for hosted deployments.",
            host,
        )
