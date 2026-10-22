import re
import socket
import ipaddress
import os
from urllib.parse import urlparse
from typing import Tuple
import httpx
from ards.models import ResourceRegistration, ResourceType

class RegistrationVerifier:
    """
    Validates resource endpoints, schemas, and probes reachability with strict SSRF protection.
    """

    @staticmethod
    def is_private_or_local(hostname: str) -> bool:
        if not hostname:
            return True
        h_lower = hostname.lower()
        if h_lower in ("localhost", "0.0.0.0", "::1"):
            return True
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if not ip.is_global:
                    return True
        except Exception:
            return True
        return False

    async def verify(self, submission: ResourceRegistration, allow_local: bool = False) -> Tuple[bool, str]:
        env_allow_local = os.getenv("ARDS_ALLOW_LOCAL", "0").lower() in ("1", "true", "yes")
        effective_allow_local = allow_local or env_allow_local

        # 1. URL syntax validation
        parsed = urlparse(submission.endpoint)
        if not parsed.scheme or not parsed.netloc or parsed.scheme not in ("http", "https"):
            return False, "INVALID_ENDPOINT: Endpoint must be a valid HTTP/HTTPS URL."

        # 2. SSRF Check
        hostname = parsed.hostname or ""
        if not effective_allow_local and self.is_private_or_local(hostname):
            return False, "SECURITY_REJECTION: Registering internal/private IP ranges, localhost, or unresolvable endpoints is prohibited."

        # 3. Type-specific verification probe
        if submission.type == ResourceType.AGENT:
            probe_url = submission.schema_url or f"{submission.endpoint.rstrip('/')}/.well-known/agent.json"
            probe_parsed = urlparse(probe_url)
            probe_host = probe_parsed.hostname or ""
            if not effective_allow_local and self.is_private_or_local(probe_host):
                return False, "SECURITY_REJECTION: Schema URL targets internal/private address."
            try:
                async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:
                    resp = await client.get(probe_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if "name" in data:
                            return True, "VERIFIED: AgentCard schema detected."
                    return True, "PROVISIONALLY_ACCEPTED: Agent responded without a valid standard AgentCard schema."
            except Exception as e:
                return True, f"UNVERIFIED: Agent endpoint registered, but initial probe failed ({str(e)})."

        return True, "ACCEPTED"

verifier = RegistrationVerifier()
