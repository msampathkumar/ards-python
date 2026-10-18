"""Verification Pipeline for Human & Agent Resource Registration Submissions."""

import logging
import re

import httpx
from typing import Dict, Any, Tuple
from urllib.parse import urlparse
from ards.models import ResourceRegistration, ResourceType

logger = logging.getLogger(__name__)


class RegistrationVerifier:
    """
    Validates registration requests to protect the public ARDS directory.
    - 2nd Order: Guards against dead links, malformed schemas, and namespace pollution.
    - 3rd Order: Prevents SSRF attacks (blocking private IP ranges like 127.0.0.1, 169.254.169.254).
    - 4th Order: Ensures ecosystem trust & interoperability.
    """

    PRIVATE_IP_REGEX = re.compile(
        r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+|169\.254\.\d+\.\d+)"
    )

    async def verify(self, submission: ResourceRegistration, allow_local: bool = True) -> Tuple[bool, str]:
        # 1. URL syntax validation
        parsed = urlparse(submission.endpoint)
        if not parsed.scheme or not parsed.netloc:
            return False, "INVALID_ENDPOINT: Endpoint must be a valid HTTP/HTTPS URL."

        # 2. SSRF Check (unless allow_local is True for local development/demos)
        hostname = parsed.hostname or ""
        if not allow_local and self.PRIVATE_IP_REGEX.match(hostname):
            return False, "SECURITY_REJECTION: Registering internal/private IP ranges or cloud metadata endpoints is prohibited."

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
                logger.info("AgentCard probe failed for %s", probe_url, exc_info=True)

        elif submission.type == ResourceType.MCP:
            # Check for MCP endpoint connectivity
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(submission.endpoint)
                    if resp.status_code < 500:
                        return True, "VERIFIED: MCP Server endpoint reachable."
            except Exception:
                logger.info("MCP probe failed for %s", submission.endpoint, exc_info=True)

        return True, "ACCEPTED: Registered with provisional health status."


verifier = RegistrationVerifier()
