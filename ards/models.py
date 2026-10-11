"""ARDS: Agent & Resource Directory Service Data Models."""

from typing import Annotated, List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
import time


class ResourceType(str, Enum):
    AGENT = "agent"
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"


class AgentCard(BaseModel):
    """Specification-compliant AgentCard model."""
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    provider: Optional[str] = None
    auth_type: str = "none"  # none, bearer, oauth2, mTLS
    metadata: Dict[str, Any] = Field(default_factory=dict)


ShortText = Annotated[str, Field(max_length=64)]


class ResourceRegistration(BaseModel):
    # Size limits keep one bad submission from bloating storage or slowing search for everyone.
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    type: ResourceType
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=4000)
    endpoint: str = Field(min_length=1, max_length=2048)
    version: str = Field(default="1.0.0", max_length=64)
    tags: List[ShortText] = Field(default_factory=list, max_length=50)
    capabilities: List[ShortText] = Field(default_factory=list, max_length=50)
    provider: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)  # e.g., Tokyo, London, Warsaw, New York, Delhi
    schema_url: Optional[str] = Field(default=None, max_length=2048)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    health_status: str = "healthy"  # healthy, provisional, degraded, unreachable
    last_verified_at: Optional[float] = None
    consecutive_failures: int = 0
    verification_message: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    type_filter: Optional[str]
    total_results: int
    execution_time_ms: float
    results: List[ResourceRegistration]
    backend: Optional[str] = None
