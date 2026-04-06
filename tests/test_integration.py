"""Integration tests for the Graph DB MCP server against a live graphserv instance.

Prerequisites:
  - graphserv running on http://localhost:8080
  - Neo4j running and connected to graphserv

Run:
  pytest tests/test_integration.py -v

All test data is prefixed with "TEST-" and cleaned up after the suite.
"""

import json
import os

import httpx
import pytest

from mcp import types as mcp_types
from mcp_servers.graph_db.server import app, GRAPHSERV

# ── Config ────────────────────────────────────────────────────────────

GRAPHSERV_BASE = os.getenv("GRAPHSERV_URL", "http://localhost:8080")
GRAPHSERV_API  = f"{GRAPHSERV_BASE}/api/v1"

# Test fixture IDs — all prefixed so cleanup is safe
APP_ID      = "TEST-app-001"
STORAGE_ID  = "TEST-storage-001"
NETWORK_ID  = "TEST-network-001"
ANOMALY_ID  = "TEST-anomaly-001"
INCIDENT_ID = "TEST-INC-001"
RCA_ID      = "TEST-RCA-001"
CHANGE_ID   = "TEST-CHG-001"


# ── MCP call helper ───────────────────────────────────────────────────

async def _call(tool_name: str, arguments: dict) -> str:
    """Invoke an MCP tool and return the text result."""
    handler = app.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=tool_name, arguments=arguments),
    )
    result = await handler(req)
    contents = result.root.content
    assert len(contents) == 1, "Expected exactly one TextContent in result"
    return contents[0].text


# ── Fixtures: seed and teardown ───────────────────────────────────────

def _graphserv_available() -> bool:
    try:
        r = httpx.get(f"{GRAPHSERV_BASE}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _create_node(label: str, props: dict) -> httpx.Response:
    return httpx.post(
        f"{GRAPHSERV_API}/nodes",
        json={"label": label, "properties": props},
        timeout=10.0,
    )


def _delete_node(label: str, node_id: str) -> None:
    httpx.delete(f"{GRAPHSERV_API}/nodes/{label}/{node_id}", timeout=10.0)


@pytest.fixture(scope="module", autouse=True)
def seed_and_teardown():
    """Seed test nodes before the suite; delete them after."""
    if not _graphserv_available():
        pytest.skip("graphserv is not running on http://localhost:8080")

    # ── Seed ──────────────────────────────────────────────────────────
    _create_node("Application", {
        "id": APP_ID, "name": "TEST PaymentsService",
        "tier": "backend", "owner": "test-team", "criticality": "high",
    })
    _create_node("Storage", {
        "id": STORAGE_ID, "name": "TEST PostgresDB",
        "type": "SQL", "capacity": "500GB",
    })
    _create_node("Network", {
        "id": NETWORK_ID, "name": "TEST VPC-prod",
        "type": "vpc", "location": "us-east-1",
    })
    _create_node("RCATicket", {
        "id": RCA_ID, "description": "TEST RCA for payment latency",
        "status": "open",
    })
    _create_node("ChangeTicket", {
        "id": CHANGE_ID,
        "description": "TEST deploy of payments-service v2.1",
        "status": "completed",
        "startTime": "2026-04-05T08:00:00Z",
        "endTime": "2026-04-05T09:00:00Z",
    })

    # Seed anomaly via /anomalies endpoint (creates DETECTED_ON edge)
    httpx.post(
        f"{GRAPHSERV_API}/anomalies",
        json={
            "id": ANOMALY_ID,
            "type": "latency_spike",
            "severity": "high",
            "status": "active",
            "startTime": "2026-04-05T09:55:00Z",
            "detectedOn": [{"label": "Application", "id": APP_ID}],
        },
        timeout=10.0,
    )

    # Seed relationships
    httpx.post(f"{GRAPHSERV_API}/relationships", json={
        "from": {"label": "Application", "id": APP_ID},
        "to":   {"label": "Storage",     "id": STORAGE_ID},
        "type": "USES_STORAGE",
    }, timeout=10.0)

    httpx.post(f"{GRAPHSERV_API}/relationships", json={
        "from": {"label": "Application", "id": APP_ID},
        "to":   {"label": "Network",     "id": NETWORK_ID},
        "type": "CONNECTS_TO",
    }, timeout=10.0)

    yield  # ── run tests ──────────────────────────────────────────────

    # ── Teardown ──────────────────────────────────────────────────────
    for label, node_id in [
        ("IncidentTicket", INCIDENT_ID),
        ("Anomaly",        ANOMALY_ID),
        ("Application",    APP_ID),
        ("Storage",        STORAGE_ID),
        ("Network",        NETWORK_ID),
        ("RCATicket",      RCA_ID),
        ("ChangeTicket",   CHANGE_ID),
    ]:
        _delete_node(label, node_id)


# ── Tests ─────────────────────────────────────────────────────────────

class TestGraphservHealth:
    """Sanity check — confirm graphserv is reachable before running tools."""

    def test_health_endpoint(self):
        r = httpx.get(f"{GRAPHSERV_BASE}/health", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"

    def test_api_root_lists_endpoints(self):
        r = httpx.get(f"{GRAPHSERV_API}", timeout=5.0)
        assert r.status_code == 200


class TestListAnomalies:
    """Tool 1 — list_anomalies"""

    async def test_returns_list(self):
        text = await _call("list_anomalies", {})
        data = json.loads(text)
        assert isinstance(data, list)

    async def test_seeded_anomaly_present(self):
        text = await _call("list_anomalies", {"limit": 100})
        assert ANOMALY_ID in text

    async def test_limit_is_respected(self):
        text = await _call("list_anomalies", {"limit": 1})
        data = json.loads(text)
        assert len(data) <= 1


class TestGetNode:
    """Tool 2 — get_node"""

    async def test_get_application_node(self):
        text = await _call("get_node", {"label": "Application", "id": APP_ID})
        data = json.loads(text)
        assert data["id"] == APP_ID
        assert data["name"] == "TEST PaymentsService"

    async def test_get_storage_node(self):
        text = await _call("get_node", {"label": "Storage", "id": STORAGE_ID})
        data = json.loads(text)
        assert data["id"] == STORAGE_ID

    async def test_get_network_node(self):
        text = await _call("get_node", {"label": "Network", "id": NETWORK_ID})
        data = json.loads(text)
        assert data["id"] == NETWORK_ID

    async def test_not_found_returns_error(self):
        text = await _call("get_node", {"label": "Application", "id": "NONEXISTENT"})
        data = json.loads(text)
        assert "status_code" in data
        assert data["status_code"] == 404


class TestRootCauseAnalysis:
    """Tool 3 — root_cause_analysis"""

    async def test_returns_result_structure(self):
        text = await _call("root_cause_analysis", {
            "startLabel": "Application",
            "startId": APP_ID,
        })
        data = json.loads(text)
        # graphserv returns origins + candidates
        assert "origins" in data or "candidates" in data

    async def test_finds_anomaly_on_app(self):
        text = await _call("root_cause_analysis", {
            "startLabel": "Application",
            "startId": APP_ID,
            "maxDepth": 3,
            "anomalyStatus": "active",
        })
        # The seeded anomaly is DETECTED_ON the test app
        assert ANOMALY_ID in text

    async def test_deep_traversal(self):
        text = await _call("root_cause_analysis", {
            "startLabel": "Application",
            "startId": APP_ID,
            "maxDepth": 10,
        })
        data = json.loads(text)
        assert isinstance(data, dict)

    async def test_unknown_node_returns_error(self):
        text = await _call("root_cause_analysis", {
            "startLabel": "Application",
            "startId": "NONEXISTENT",
        })
        data = json.loads(text)
        assert "status_code" in data


class TestBlastRadius:
    """Tool 4 — blast_radius"""

    async def test_returns_impact_metrics(self):
        text = await _call("blast_radius", {
            "label": "Storage",
            "id": STORAGE_ID,
        })
        data = json.loads(text)
        assert isinstance(data, dict)

    async def test_app_depends_on_storage(self):
        # The test app uses the test storage, so storage blast radius >= 1
        text = await _call("blast_radius", {
            "label": "Storage",
            "id": STORAGE_ID,
            "useTransitive": "false",
        })
        data = json.loads(text)
        # dependentCount or similar key should be present
        assert any(k in data for k in ("dependentCount", "dependents", "impactedNodes"))

    async def test_with_transitive_edges(self):
        text = await _call("blast_radius", {
            "label": "Network",
            "id": NETWORK_ID,
            "useTransitive": "true",
        })
        data = json.loads(text)
        assert isinstance(data, dict)


class TestGetRelationships:
    """Tool 5 — get_relationships"""

    async def test_app_uses_storage(self):
        text = await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": APP_ID,
            "type": "USES_STORAGE",
        })
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_app_connects_to_network(self):
        text = await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": APP_ID,
            "type": "CONNECTS_TO",
        })
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_no_relationship_returns_empty(self):
        text = await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": APP_ID,
            "type": "CALLS",
        })
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_with_optional_target_filter(self):
        text = await _call("get_relationships", {
            "fromLabel": "Application",
            "fromId": APP_ID,
            "type": "USES_STORAGE",
            "toLabel": "Storage",
            "toId": STORAGE_ID,
        })
        data = json.loads(text)
        assert isinstance(data, list)


class TestCreateIncidentTicket:
    """Tool 6 — create_incident_ticket"""

    async def test_creates_ticket(self):
        text = await _call("create_incident_ticket", {
            "id": INCIDENT_ID,
            "severity": "SEV2",
            "status": "open",
            "startTime": "2026-04-05T10:00:00Z",
        })
        data = json.loads(text)
        assert data.get("id") == INCIDENT_ID

    async def test_idempotent_merge(self):
        # Calling again with same id should not error (MERGE behaviour)
        text = await _call("create_incident_ticket", {
            "id": INCIDENT_ID,
            "severity": "SEV2",
            "status": "investigating",
        })
        data = json.loads(text)
        assert "status_code" not in data or data["status_code"] < 400

    async def test_ticket_retrievable_after_creation(self):
        text = await _call("get_node", {"label": "IncidentTicket", "id": INCIDENT_ID})
        data = json.loads(text)
        assert data["id"] == INCIDENT_ID


class TestLinkIncidentToNode:
    """Tool 7 — link_incident_to_node"""

    async def test_links_to_application(self):
        text = await _call("link_incident_to_node", {
            "fromId": INCIDENT_ID,
            "toLabel": "Application",
            "toId": APP_ID,
        })
        data = json.loads(text)
        assert "status_code" not in data or data["status_code"] < 400

    async def test_relationship_exists_after_link(self):
        # Verify the IMPACTS relationship was created
        text = await _call("get_relationships", {
            "fromLabel": "IncidentTicket",
            "fromId": INCIDENT_ID,
            "type": "IMPACTS",
        })
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) >= 1


class TestGetRCATickets:
    """Tool 8 — get_rca_tickets"""

    async def test_returns_list(self):
        text = await _call("get_rca_tickets", {})
        data = json.loads(text)
        assert isinstance(data, list)

    async def test_seeded_rca_ticket_present(self):
        text = await _call("get_rca_tickets", {"limit": 100})
        assert RCA_ID in text

    async def test_limit_respected(self):
        text = await _call("get_rca_tickets", {"limit": 1})
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) <= 1


class TestGetChangeTickets:
    """Tool 9 — get_change_tickets"""

    async def test_returns_list(self):
        text = await _call("get_change_tickets", {})
        data = json.loads(text)
        assert isinstance(data, list)

    async def test_seeded_change_ticket_present(self):
        text = await _call("get_change_tickets", {"limit": 100})
        assert CHANGE_ID in text

    async def test_limit_respected(self):
        text = await _call("get_change_tickets", {"limit": 1})
        data = json.loads(text)
        assert len(data) <= 1


class TestUpdateNodeStatus:
    """Tool 10 — update_node_status"""

    async def test_updates_incident_status(self):
        text = await _call("update_node_status", {
            "label": "IncidentTicket",
            "id": INCIDENT_ID,
            "status": "investigating",
        })
        data = json.loads(text)
        assert "status_code" not in data or data["status_code"] < 400

    async def test_status_reflected_on_get(self):
        await _call("update_node_status", {
            "label": "IncidentTicket",
            "id": INCIDENT_ID,
            "status": "mitigating",
        })
        text = await _call("get_node", {
            "label": "IncidentTicket",
            "id": INCIDENT_ID,
        })
        assert "mitigating" in text

    async def test_update_anomaly_status(self):
        text = await _call("update_node_status", {
            "label": "Anomaly",
            "id": ANOMALY_ID,
            "status": "resolved",
        })
        data = json.loads(text)
        assert "status_code" not in data or data["status_code"] < 400

    async def test_not_found_returns_404(self):
        text = await _call("update_node_status", {
            "label": "Application",
            "id": "NONEXISTENT",
            "status": "resolved",
        })
        data = json.loads(text)
        assert data["status_code"] == 404
