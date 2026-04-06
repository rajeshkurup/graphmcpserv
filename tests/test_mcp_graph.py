"""Unit tests for the Graph DB MCP server.

Every tool is tested against a mocked graphserv backend using respx.
"""

import json

import httpx
import pytest
import respx
from mcp import types as mcp_types

from mcp_servers.graph_db.server import app, GRAPHSERV

# ── Helpers ───────────────────────────────────────────────────────────


async def _call(tool_name: str, arguments: dict) -> str:
    """Invoke a tool on the MCP server and return the text result."""
    handler = app.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=tool_name, arguments=arguments),
    )
    result = await handler(req)
    contents = result.root.content
    assert len(contents) == 1
    return contents[0].text


async def _list_tool_names() -> list[str]:
    handler = app.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = await handler(req)
    return [t.name for t in result.root.tools]


async def _list_tools() -> list:
    handler = app.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = await handler(req)
    return result.root.tools


# ── Tool catalogue ────────────────────────────────────────────────────


class TestToolCatalogue:
    async def test_lists_all_ten_tools(self):
        names = await _list_tool_names()
        assert len(names) == 10

    async def test_expected_tool_names(self):
        names = set(await _list_tool_names())
        expected = {
            "list_anomalies", "get_node", "root_cause_analysis",
            "blast_radius", "get_relationships", "create_incident_ticket",
            "link_incident_to_node", "get_rca_tickets", "get_change_tickets",
            "update_node_status",
        }
        assert names == expected

    async def test_all_tools_have_input_schema(self):
        tools = await _list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"


# ── list_anomalies ────────────────────────────────────────────────────


class TestListAnomalies:
    @respx.mock
    async def test_returns_anomalies(self):
        payload = {"nodes": [{"id": "ANOM-1", "status": "open"}]}
        respx.get(f"{GRAPHSERV}/nodes/Anomaly").mock(
            return_value=httpx.Response(200, json=payload),
        )
        text = await _call("list_anomalies", {"limit": 10})
        assert "ANOM-1" in text

    @respx.mock
    async def test_passes_limit_param(self):
        route = respx.get(f"{GRAPHSERV}/nodes/Anomaly").mock(
            return_value=httpx.Response(200, json={"nodes": []}),
        )
        await _call("list_anomalies", {"limit": 5})
        assert route.called
        assert route.calls[0].request.url.params["limit"] == "5"

    @respx.mock
    async def test_no_params_when_empty(self):
        route = respx.get(f"{GRAPHSERV}/nodes/Anomaly").mock(
            return_value=httpx.Response(200, json={"nodes": []}),
        )
        await _call("list_anomalies", {})
        assert route.called


# ── get_node ──────────────────────────────────────────────────────────


class TestGetNode:
    @respx.mock
    async def test_returns_node(self):
        node = {"id": "app-1", "name": "payments"}
        respx.get(f"{GRAPHSERV}/nodes/Application/app-1").mock(
            return_value=httpx.Response(200, json=node),
        )
        text = await _call("get_node", {"label": "Application", "id": "app-1"})
        assert "payments" in text

    @respx.mock
    async def test_not_found(self):
        respx.get(f"{GRAPHSERV}/nodes/Application/missing").mock(
            return_value=httpx.Response(404, json={"error": "not found"}),
        )
        text = await _call("get_node", {"label": "Application", "id": "missing"})
        parsed = json.loads(text)
        assert parsed["status_code"] == 404


# ── root_cause_analysis ──────────────────────────────────────────────


class TestRootCauseAnalysis:
    @respx.mock
    async def test_posts_correct_body(self):
        respx.get(f"{GRAPHSERV}/nodes/Application/app-1").mock(
            return_value=httpx.Response(200, json={"id": "app-1"}),
        )
        result = {"candidates": 2, "origins": []}
        route = respx.post(f"{GRAPHSERV}/analysis/root-cause").mock(
            return_value=httpx.Response(200, json=result),
        )
        text = await _call("root_cause_analysis", {
            "startLabel": "Application",
            "startId": "app-1",
            "maxDepth": 3,
        })
        body = json.loads(route.calls[0].request.content)
        assert body["startLabel"] == "Application"
        assert body["startId"] == "app-1"
        assert body["maxDepth"] == 3
        assert body["anomalyStatus"] == "active"  # default
        assert "candidates" in text

    @respx.mock
    async def test_defaults_applied(self):
        respx.get(f"{GRAPHSERV}/nodes/Storage/db-1").mock(
            return_value=httpx.Response(200, json={"id": "db-1"}),
        )
        route = respx.post(f"{GRAPHSERV}/analysis/root-cause").mock(
            return_value=httpx.Response(200, json={}),
        )
        await _call("root_cause_analysis", {
            "startLabel": "Storage",
            "startId": "db-1",
        })
        body = json.loads(route.calls[0].request.content)
        assert body["maxDepth"] == 5
        assert body["limit"] == 50


# ── blast_radius ─────────────────────────────────────────────────────


class TestBlastRadius:
    @respx.mock
    async def test_sends_query_params(self):
        metrics = {"dependentCount": 12, "dependents": []}
        route = respx.get(f"{GRAPHSERV}/analysis/impact").mock(
            return_value=httpx.Response(200, json=metrics),
        )
        text = await _call("blast_radius", {
            "label": "Application",
            "id": "app-1",
            "useTransitive": "true",
        })
        params = route.calls[0].request.url.params
        assert params["label"] == "Application"
        assert params["id"] == "app-1"
        assert params["useTransitive"] == "true"
        assert "dependentCount" in text


# ── get_relationships ────────────────────────────────────────────────


class TestGetRelationships:
    @respx.mock
    async def test_required_params(self):
        route = respx.get(f"{GRAPHSERV}/relationships").mock(
            return_value=httpx.Response(200, json={"relationships": []}),
        )
        await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": "app-1",
            "type": "CALLS",
        })
        params = route.calls[0].request.url.params
        assert params["fromLabel"] == "Application"
        assert params["type"] == "CALLS"

    @respx.mock
    async def test_optional_target_filter(self):
        route = respx.get(f"{GRAPHSERV}/relationships").mock(
            return_value=httpx.Response(200, json={"relationships": []}),
        )
        await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": "app-1",
            "type": "CALLS",
            "toLabel": "Storage",
            "toId": "db-1",
        })
        params = route.calls[0].request.url.params
        assert params["toLabel"] == "Storage"
        assert params["toId"] == "db-1"


# ── create_incident_ticket ───────────────────────────────────────────


class TestCreateIncidentTicket:
    @respx.mock
    async def test_creates_ticket(self):
        route = respx.post(f"{GRAPHSERV}/nodes").mock(
            return_value=httpx.Response(201, json={"id": "INC-001"}),
        )
        text = await _call("create_incident_ticket", {
            "id": "INC-001",
            "severity": "SEV1",
            "status": "open",
            "startTime": "2026-04-05T10:00:00Z",
        })
        body = json.loads(route.calls[0].request.content)
        assert body["label"] == "IncidentTicket"
        assert body["properties"]["id"] == "INC-001"
        assert body["properties"]["severity"] == "SEV1"
        assert body["properties"]["startTime"] == "2026-04-05T10:00:00Z"
        assert "INC-001" in text

    @respx.mock
    async def test_without_start_time(self):
        route = respx.post(f"{GRAPHSERV}/nodes").mock(
            return_value=httpx.Response(201, json={}),
        )
        await _call("create_incident_ticket", {
            "id": "INC-002",
            "severity": "SEV2",
            "status": "investigating",
        })
        body = json.loads(route.calls[0].request.content)
        assert "startTime" not in body["properties"]


# ── link_incident_to_node ────────────────────────────────────────────


class TestLinkIncidentToNode:
    @respx.mock
    async def test_creates_impacts_relationship(self):
        route = respx.post(f"{GRAPHSERV}/relationships").mock(
            return_value=httpx.Response(201, json={"type": "IMPACTS"}),
        )
        text = await _call("link_incident_to_node", {
            "fromId": "INC-001",
            "toLabel": "Application",
            "toId": "app-1",
        })
        body = json.loads(route.calls[0].request.content)
        assert body["from"] == {"label": "IncidentTicket", "id": "INC-001"}
        assert body["to"] == {"label": "Application", "id": "app-1"}
        assert body["type"] == "IMPACTS"
        assert "IMPACTS" in text


# ── get_rca_tickets ──────────────────────────────────────────────────


class TestGetRCATickets:
    @respx.mock
    async def test_returns_tickets(self):
        payload = {"nodes": [{"id": "RCA-1"}]}
        respx.get(f"{GRAPHSERV}/nodes/RCATicket").mock(
            return_value=httpx.Response(200, json=payload),
        )
        text = await _call("get_rca_tickets", {"limit": 10})
        assert "RCA-1" in text


# ── get_change_tickets ───────────────────────────────────────────────


class TestGetChangeTickets:
    @respx.mock
    async def test_returns_tickets(self):
        payload = {"nodes": [{"id": "CHG-1"}]}
        respx.get(f"{GRAPHSERV}/nodes/ChangeTicket").mock(
            return_value=httpx.Response(200, json=payload),
        )
        text = await _call("get_change_tickets", {"limit": 5})
        assert "CHG-1" in text


# ── update_node_status ───────────────────────────────────────────────


class TestUpdateNodeStatus:
    @respx.mock
    async def test_patches_status(self):
        route = respx.patch(f"{GRAPHSERV}/nodes/IncidentTicket/INC-001").mock(
            return_value=httpx.Response(200, json={"status": "resolved"}),
        )
        text = await _call("update_node_status", {
            "label": "IncidentTicket",
            "id": "INC-001",
            "status": "resolved",
        })
        body = json.loads(route.calls[0].request.content)
        assert body == {"status": "resolved"}
        assert "resolved" in text

    @respx.mock
    async def test_not_found_error(self):
        respx.patch(f"{GRAPHSERV}/nodes/Application/missing").mock(
            return_value=httpx.Response(404, json={"error": "not found"}),
        )
        text = await _call("update_node_status", {
            "label": "Application",
            "id": "missing",
            "status": "resolved",
        })
        parsed = json.loads(text)
        assert parsed["status_code"] == 404


# ── unknown tool ─────────────────────────────────────────────────────


class TestUnknownTool:
    async def test_returns_error_for_unknown_tool(self):
        text = await _call("nonexistent_tool", {})
        assert "error" in text.lower() or "unknown" in text.lower()
