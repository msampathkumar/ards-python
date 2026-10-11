"""Native MCP & A2A Endpoints for ARDS Directory Service.
Allows external agents and users to connect to ARDS via MCP or A2A and ask relevant questions.
"""

from typing import Dict, Any, List
from fastapi import APIRouter
from pydantic import BaseModel

from ards.models import ResourceType
from ards.registry import registry

router = APIRouter(tags=["interfaces"])


# --- A2A PROTOCOL INTERFACE ---
class A2ATaskMessage(BaseModel):
    role: str = "user"
    content: str


class A2ATaskRequest(BaseModel):
    id: str
    message: A2ATaskMessage


@router.get("/.well-known/agent.json")
async def get_ards_agent_card():
    """Returns official A2A AgentCard for ARDS Directory Service."""
    return {
        "name": "ARDS Discovery Gateway Agent",
        "description": "Autonomous directory interface for discovering agents, MCP tools, and skills across multi-agent meshes.",
        "version": "1.0.0",
        "protocol": "A2A/0.2.0",
        "capabilities": ["search_directory", "resolve_agentcard", "recommend_tools"],
        "endpoints": {"tasks": "/a2a/tasks"},
    }


@router.post("/a2a/tasks")
async def handle_a2a_task(task: A2ATaskRequest):
    """Processes natural language discovery requests from external A2A agents."""
    query = task.message.content.strip()
    resp = registry.search(query=query)

    if resp.results:
        summary_lines = [f"Found {resp.total_results} matching resources in ARDS ({resp.execution_time_ms} ms):"]
        for r in resp.results[:5]:
            summary_lines.append(f"• [{r.type.value.upper()}] {r.name} ({r.endpoint}) - {r.description}")
        reply_text = "\n".join(summary_lines)
    else:
        reply_text = f"No matching agents or tools found in ARDS for query: '{query}'."

    return {
        "id": task.id,
        "status": "completed",
        "result": {
            "role": "agent",
            "content": reply_text,
            "data": [r.model_dump() for r in resp.results[:5]],
        },
    }


# --- MODEL CONTEXT PROTOCOL (MCP) INTERFACE ---
@router.get("/mcp/tools")
async def list_mcp_tools():
    """Lists MCP tools provided by ARDS."""
    return {
        "tools": [
            {
                "name": "search_directory",
                "description": "Searches ARDS for registered agents, MCP database servers, skills, and plugins by keyword, capability, or location.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword or natural language intent"},
                        "type_filter": {"type": "string", "enum": ["agent", "mcp", "skill", "plugin"], "description": "Optional type filter"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_resource_details",
                "description": "Fetches full metadata and endpoints for a specific resource ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"resource_id": {"type": "string"}},
                    "required": ["resource_id"],
                },
            },
        ]
    }


@router.post("/mcp/execute")
async def execute_mcp_tool(payload: Dict[str, Any]):
    """Executes an ARDS MCP tool call."""
    tool_name = payload.get("name")
    args = payload.get("arguments", {})

    if tool_name == "search_directory":
        q = str(args.get("query", ""))[:256]
        t = args.get("type_filter")
        try:
            type_filter = ResourceType(t) if t else None
        except ValueError:
            return {"error": f"Invalid type_filter '{t}'. Use one of: agent, mcp, skill, plugin."}
        res = registry.search(query=q, type_filter=type_filter, limit=50)
        return {"total": res.total_results, "results": [r.model_dump() for r in res.results]}

    elif tool_name == "get_resource_details":
        res_id = args.get("resource_id", "")
        item = registry.get(res_id)
        if item:
            return {"found": True, "resource": item.model_dump()}
        return {"found": False, "error": f"Resource {res_id} not found"}

    return {"error": f"Unknown tool: {tool_name}"}
