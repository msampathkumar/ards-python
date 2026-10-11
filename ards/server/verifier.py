"""Verification Pipeline for Human & Agent Resource Registration Submissions."""

import asyncio
import ipaddress
import socket
import httpx
import re
from typing import Dict, Any, Tuple
from urllib.parse import urlparse
from ards.models import ResourceRegistration, ResourceType

ALLOWED_SCHEMES = ("http", "https")


def is_safe_http_url(url: str) -> bool:
    """True if `url` is an absolute http(s) URL. Blocks `javascript:`, `data:`, `file:` and similar schemes."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme.lower() in ALLOWED_SCHEMES and bool(parsed.netloc)


def _is_internal_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


class RegistrationVerifier:
    """
    Validates registration requests to protect the public ARDS directory.
    - 2nd Order: Guards against dead links, malformed schemas, and namespace pollution.
    - 3rd Order: Prevents SSRF attacks (blocking private IP ranges like 127.0.0.1, 169.254.169.254).
    - 4th Order: Ensures ecosystem trust & interoperability.
    """

    # Deprecated: hostname regex missed IPv6 (::1), 0.0.0.0 and DNS names that resolve to private IPs.
    # Kept for backward compatibility; `_host_is_internal` is now used instead.
    PRIVATE_IP_REGEX = re.compile(
        r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+|169\.254\.\d+\.\d+)"
    )

    async def _host_is_internal(self, hostname: str) -> bool:
        host = hostname.strip("[]").lower()
        if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
            return True
        if _is_internal_ip(host):
            return True
        # Resolve DNS names: a public-looking name can still point at a private IP.
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except (socket.gaierror, UnicodeError, OSError):
            return False  # Unresolvable hosts are reported as unreachable by health probes, not as SSRF.
        return any(_is_internal_ip(info[4][0]) for info in infos)

    async def check_url_policy(self, submission: ResourceRegistration, allow_local: bool = True) -> Tuple[bool, str]:
        """Cheap, network-free (except DNS) policy check: URL scheme and SSRF rules. No endpoint probing."""
        if not is_safe_http_url(submission.endpoint):
            return False, "INVALID_ENDPOINT: Endpoint must be an absolute http:// or https:// URL."
        if submission.schema_url and not is_safe_http_url(submission.schema_url):
            return False, "INVALID_SCHEMA_URL: schema_url must be an absolute http:// or https:// URL."

        if not allow_local:
            for url in filter(None, (submission.endpoint, submission.schema_url)):
                hostname = urlparse(url).hostname or ""
                if await self._host_is_internal(hostname):
                    return False, (
                        "SECURITY_REJECTION: Registering internal/private IP ranges or "
                        "cloud metadata endpoints is prohibited."
                    )
        return True, "POLICY_OK"

    async def verify(self, submission: ResourceRegistration, allow_local: bool = True) -> Tuple[bool, str]:
        # 1 & 2. URL syntax + SSRF policy
        ok, msg = await self.check_url_policy(submission, allow_local=allow_local)
        if not ok:
            return False, msg

        # 3. Type-specific verification probe
        if submission.type == ResourceType.AGENT:
            # Probe AgentCard schema if schema_url provided
            probe_url = submission.schema_url or f"{submission.endpoint.rstrip('/')}/.well-known/agent.json"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(probe_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if "name" in data or "capabilities" in data or "protocol" in data:
                            return True, "VERIFIED: AgentCard successfully validated."
            except Exception:
                # Fallback to accepting registration with 'unverified' trust badge
                pass

        elif submission.type == ResourceType.MCP:
            # Check for MCP endpoint connectivity
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(submission.endpoint)
                    if resp.status_code < 500:
                        return True, "VERIFIED: MCP Server endpoint reachable."
            except Exception:
                pass

        return True, "ACCEPTED: Registered with provisional health status."


verifier = RegistrationVerifier()
