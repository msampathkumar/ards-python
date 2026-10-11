"""ARDS: Agent & Resource Directory Service Data Models."""

from typing import List, Optional, Dict, Any
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


class ResourceRegistration(BaseModel):
    id: str
    type: ResourceType
    name: str
    description: str
    endpoint: str
    version: str = "1.0.0"
    tags: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    provider: Optional[str] = None
    location: Optional[str] = None  # e.g., Tokyo, London, Warsaw, New York, Delhi
    schema_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    health_status: str = "healthy"  # healthy, degraded, unreachable


class SearchResponse(BaseModel):
    query: str
    type_filter: Optional[str]
    total_results: int
    execution_time_ms: float
    results: List[ResourceRegistration]
