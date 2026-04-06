"""Graph DB MCP Server — wraps the graphserv REST API.

Exposes 10 tools that let LangGraph agents interact with the Neo4j
topology graph without touching the database directly.
"""

import asyncio
import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

GRAPHSERV_BASE = os.getenv("GRAPHSERV_URL", "http://localhost:8080")
GRAPHSERV = f"{GRAPHSERV_BASE}/api/v1"
HTTP_TIMEOUT = float(os.getenv("GRAPHSERV_TIMEOUT", "10.0"))

VALID_NODE_LABELS = [
    "Application", "Storage", "Network", "IncidentTicket",
    "ChangeTicket", "RCATicket", "Action", "Anomaly", "Call",
]

VALID_REL_TYPES = [
    "CALLS", "USES_STORAGE", "CONNECTS_TO", "STORED_ON_NETWORK",
    "IMPACTS", "AFFECTS", "ROOT_CAUSE_OF", "HAS_ACTION", "TO",
    "DEPENDS_ON_TRANSITIVE", "DETECTED_ON",
]

app = Server("graph-db-mcp")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT)


def _text_result(text: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=text)]


async def _forward_response(resp: httpx.Response) -> list[types.TextContent]:
    """Return the response body; include status on errors."""
    if resp.is_success:
        return _text_result(resp.text)
    return _text_result(json.dumps({
        "error": resp.text,
        "status_code": resp.status_code,
    }))


async def _forward_list_response(
    resp: httpx.Response, key: str,
) -> list[types.TextContent]:
    """Return the response body, unwrapping a ``{key: [...]}`` wrapper if present."""
    if not resp.is_success:
        return _text_result(json.dumps({
            "error": resp.text,
            "status_code": resp.status_code,
        }))
    try:
        data = resp.json()
        if isinstance(data, dict) and key in data:
            return _text_result(json.dumps(data[key]))
    except (json.JSONDecodeError, ValueError):
        pass
    return _text_result(resp.text)


# ── Tool catalogue ────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        # 1. list_anomalies
        types.Tool(
            name="list_anomalies",
            description="List anomaly nodes from the topology graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "in_progress", "active"],
                        "description": "Filter anomalies by status.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximum number of anomalies to return.",
                    },
                },
            },
        ),
        # 2. get_node
        types.Tool(
            name="get_node",
            description="Get a single node by its label and business id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Node label.",
                    },
                    "id": {
                        "type": "string",
                        "description": "Node business id.",
                    },
                },
                "required": ["label", "id"],
            },
        ),
        # 3. root_cause_analysis
        types.Tool(
            name="root_cause_analysis",
            description="Traverse downstream from a start node to find active anomalies (root cause candidates).",
            inputSchema={
                "type": "object",
                "properties": {
                    "startLabel": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Label of the start node.",
                    },
                    "startId": {
                        "type": "string",
                        "description": "Business id of the start node.",
                    },
                    "maxDepth": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum traversal depth.",
                    },
                    "anomalyStatus": {
                        "type": "string",
                        "default": "active",
                        "description": "Status of anomalies to look for.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of root cause candidates.",
                    },
                },
                "required": ["startLabel", "startId"],
            },
        ),
        # 4. blast_radius
        types.Tool(
            name="blast_radius",
            description="Compute blast radius / impact analysis for a node — how many other nodes depend on it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Node label.",
                    },
                    "id": {
                        "type": "string",
                        "description": "Node business id.",
                    },
                    "useTransitive": {
                        "type": "string",
                        "enum": ["true", "false"],
                        "default": "false",
                        "description": "Use precomputed DEPENDS_ON_TRANSITIVE edges.",
                    },
                },
                "required": ["label", "id"],
            },
        ),
        # 5. get_relationships
        types.Tool(
            name="get_relationships",
            description="List relationships of a given type from a source node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "fromLabel": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Source node label.",
                    },
                    "fromId": {
                        "type": "string",
                        "description": "Source node id.",
                    },
                    "type": {
                        "type": "string",
                        "enum": VALID_REL_TYPES,
                        "description": "Relationship type.",
                    },
                    "toLabel": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Optional target node label filter.",
                    },
                    "toId": {
                        "type": "string",
                        "description": "Optional target node id filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum number of relationships.",
                    },
                },
                "required": ["fromLabel", "fromId", "type"],
            },
        ),
        # 6. create_incident_ticket
        types.Tool(
            name="create_incident_ticket",
            description="Create or merge an IncidentTicket node in the topology graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Ticket business id (e.g. INC-001).",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["SEV1", "SEV2", "SEV3", "SEV4"],
                        "description": "Incident severity level.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "investigating", "mitigating", "resolved"],
                        "description": "Ticket status.",
                    },
                    "startTime": {
                        "type": "string",
                        "description": "ISO-8601 timestamp when the incident started.",
                    },
                },
                "required": ["id", "severity", "status"],
            },
        ),
        # 7. link_incident_to_node
        types.Tool(
            name="link_incident_to_node",
            description="Create an IMPACTS relationship from an IncidentTicket to another topology node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "fromId": {
                        "type": "string",
                        "description": "IncidentTicket business id.",
                    },
                    "toLabel": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Target node label.",
                    },
                    "toId": {
                        "type": "string",
                        "description": "Target node business id.",
                    },
                },
                "required": ["fromId", "toLabel", "toId"],
            },
        ),
        # 8. get_rca_tickets
        types.Tool(
            name="get_rca_tickets",
            description="List RCATicket nodes from the topology graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by ticket status.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum number of tickets.",
                    },
                },
            },
        ),
        # 9. get_change_tickets
        types.Tool(
            name="get_change_tickets",
            description="List ChangeTicket nodes from the topology graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by ticket status.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum number of tickets.",
                    },
                },
            },
        ),
        # 10. update_node_status
        types.Tool(
            name="update_node_status",
            description="Update the status property of a node via PATCH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": VALID_NODE_LABELS,
                        "description": "Node label.",
                    },
                    "id": {
                        "type": "string",
                        "description": "Node business id.",
                    },
                    "status": {
                        "type": "string",
                        "description": "New status value.",
                    },
                },
                "required": ["label", "id", "status"],
            },
        ),
    ]


# ── Tool dispatcher ───────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with _client() as client:
        if name == "list_anomalies":
            params: dict = {}
            if "limit" in arguments:
                params["limit"] = arguments["limit"]
            if "status" in arguments:
                params["status"] = arguments["status"]
            resp = await client.get(f"{GRAPHSERV}/nodes/Anomaly", params=params)
            return await _forward_list_response(resp, "nodes")

        if name == "get_node":
            label = arguments["label"]
            node_id = arguments["id"]
            resp = await client.get(f"{GRAPHSERV}/nodes/{label}/{node_id}")
            return await _forward_response(resp)

        if name == "root_cause_analysis":
            # Verify the start node exists before running analysis
            check = await client.get(
                f"{GRAPHSERV}/nodes/{arguments['startLabel']}/{arguments['startId']}",
            )
            if not check.is_success:
                return await _forward_response(check)
            body = {
                "startLabel": arguments["startLabel"],
                "startId": arguments["startId"],
                "maxDepth": arguments.get("maxDepth", 5),
                "anomalyStatus": arguments.get("anomalyStatus", "active"),
                "limit": arguments.get("limit", 50),
            }
            resp = await client.post(f"{GRAPHSERV}/analysis/root-cause", json=body)
            return await _forward_response(resp)

        if name == "blast_radius":
            params = {
                "label": arguments["label"],
                "id": arguments["id"],
                "useTransitive": arguments.get("useTransitive", "false"),
            }
            resp = await client.get(f"{GRAPHSERV}/analysis/impact", params=params)
            return await _forward_response(resp)

        if name == "get_relationships":
            params = {
                "fromLabel": arguments["fromLabel"],
                "fromId": arguments["fromId"],
                "type": arguments["type"],
            }
            for key in ("toLabel", "toId", "limit"):
                if key in arguments:
                    params[key] = arguments[key]
            resp = await client.get(f"{GRAPHSERV}/relationships", params=params)
            return await _forward_list_response(resp, "relationships")

        if name == "create_incident_ticket":
            body = {
                "label": "IncidentTicket",
                "properties": {
                    "id": arguments["id"],
                    "severity": arguments["severity"],
                    "status": arguments["status"],
                },
            }
            if "startTime" in arguments:
                body["properties"]["startTime"] = arguments["startTime"]
            resp = await client.post(f"{GRAPHSERV}/nodes", json=body)
            return await _forward_response(resp)

        if name == "link_incident_to_node":
            body = {
                "from": {"label": "IncidentTicket", "id": arguments["fromId"]},
                "to": {"label": arguments["toLabel"], "id": arguments["toId"]},
                "type": "IMPACTS",
            }
            resp = await client.post(f"{GRAPHSERV}/relationships", json=body)
            return await _forward_response(resp)

        if name == "get_rca_tickets":
            params = {}
            if "limit" in arguments:
                params["limit"] = arguments["limit"]
            resp = await client.get(f"{GRAPHSERV}/nodes/RCATicket", params=params)
            return await _forward_list_response(resp, "nodes")

        if name == "get_change_tickets":
            params = {}
            if "limit" in arguments:
                params["limit"] = arguments["limit"]
            resp = await client.get(f"{GRAPHSERV}/nodes/ChangeTicket", params=params)
            return await _forward_list_response(resp, "nodes")

        if name == "update_node_status":
            label = arguments["label"]
            node_id = arguments["id"]
            body = {"status": arguments["status"]}
            resp = await client.patch(
                f"{GRAPHSERV}/nodes/{label}/{node_id}", json=body,
            )
            return await _forward_response(resp)

    raise ValueError(f"unknown tool: {name}")


# ── Entry point ───────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
