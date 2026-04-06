# GraphMCP Server

An MCP (Model Context Protocol) server that exposes Neo4j topology graph operations through the [graphserv](http://graphserv) REST API. It enables AI agents (e.g. LangGraph) to query, traverse, and mutate a topology graph without direct database access.

## Architecture

```
┌──────────────┐       stdio        ┌────────────────┐      HTTP/REST     ┌────────────┐
│   AI Agent   │ ◄────────────────► │  GraphMCP      │ ◄────────────────► │  graphserv │
│ (LangGraph)  │   MCP Protocol     │  Server        │   /api/v1/*        │  (Neo4j)   │
└──────────────┘                    └────────────────┘                    └────────────┘
```

The server communicates with clients over **stdio** (standard MCP transport) and forwards requests to the graphserv REST API over HTTP.

## Quick Start

### Prerequisites

- Python >= 3.11
- A running [graphserv](http://graphserv) instance

### Installation

```bash
# Install the package
pip install .

# Or install with dev dependencies (pytest, respx)
pip install ".[dev]"
```

### Configuration

Copy the example env file and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `GRAPHSERV_URL` | Base URL of the graphserv REST API | `http://localhost:8080` |
| `GRAPHSERV_TIMEOUT` | HTTP request timeout (seconds) | `10.0` |

### Running

```bash
python -m mcp_servers.graph_db.server
```

### Docker

```bash
docker build -t graphmcpserv .
docker run -e GRAPHSERV_URL=http://graphserv:8080 graphmcpserv
```

## MCP Client Configuration

To use this server with an MCP-compatible client, add it to your client configuration:

```json
{
  "mcpServers": {
    "graphmcpserv": {
      "command": "python",
      "args": ["-m", "mcp_servers.graph_db.server"],
      "env": {
        "GRAPHSERV_URL": "http://localhost:8080"
      }
    }
  }
}
```

## Graph Model

### Node Labels

The topology graph contains the following node types:

| Label | Description |
|---|---|
| `Application` | Application or service in the topology |
| `Storage` | Storage system (database, cache, etc.) |
| `Network` | Network component |
| `IncidentTicket` | Incident tracking ticket |
| `ChangeTicket` | Change request ticket |
| `RCATicket` | Root cause analysis ticket |
| `Action` | Remediation or follow-up action |
| `Anomaly` | Detected anomaly in the system |
| `Call` | Service-to-service call |

### Relationship Types

| Type | Description |
|---|---|
| `CALLS` | Service-to-service invocation |
| `USES_STORAGE` | Application uses a storage system |
| `CONNECTS_TO` | Network connectivity |
| `STORED_ON_NETWORK` | Storage resides on a network |
| `IMPACTS` | Incident impacts a node |
| `AFFECTS` | Anomaly affects a node |
| `ROOT_CAUSE_OF` | Identifies root cause link |
| `HAS_ACTION` | Ticket has a follow-up action |
| `TO` | Generic directed relationship |
| `DEPENDS_ON_TRANSITIVE` | Precomputed transitive dependency |
| `DETECTED_ON` | Anomaly detected on a node |

## Tools

The server exposes **10 tools** for graph operations, organized into four categories.

---

### Querying Nodes

#### `get_node`

Retrieve a single node by its label and business ID.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `label` | enum | Yes | Node label (see [Node Labels](#node-labels)) |
| `id` | string | Yes | Node business ID |

```
get_node(label="Application", id="order-service")
```

#### `list_anomalies`

List anomaly nodes from the topology graph.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | enum | No | — | Filter: `open`, `resolved`, `in_progress`, `active` |
| `limit` | integer | No | `20` | Maximum results to return |

```
list_anomalies(status="active", limit=10)
```

#### `get_rca_tickets`

List RCATicket nodes.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | string | No | — | Filter by ticket status |
| `limit` | integer | No | `100` | Maximum results to return |

#### `get_change_tickets`

List ChangeTicket nodes.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | string | No | — | Filter by ticket status |
| `limit` | integer | No | `100` | Maximum results to return |

---

### Traversal & Analysis

#### `root_cause_analysis`

Traverse downstream from a start node to find active anomalies (root cause candidates).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `startLabel` | enum | Yes | — | Label of the start node |
| `startId` | string | Yes | — | Business ID of the start node |
| `maxDepth` | integer | No | `5` | Maximum traversal depth |
| `anomalyStatus` | string | No | `"active"` | Anomaly status to match |
| `limit` | integer | No | `50` | Maximum root cause candidates |

```
root_cause_analysis(startLabel="Application", startId="order-service", maxDepth=3)
```

#### `blast_radius`

Compute impact analysis for a node — how many other nodes depend on it.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `label` | enum | Yes | — | Node label |
| `id` | string | Yes | — | Node business ID |
| `useTransitive` | enum | No | `"false"` | Use precomputed `DEPENDS_ON_TRANSITIVE` edges (`"true"` / `"false"`) |

```
blast_radius(label="Storage", id="primary-db", useTransitive="true")
```

#### `get_relationships`

List relationships of a given type from a source node.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `fromLabel` | enum | Yes | — | Source node label |
| `fromId` | string | Yes | — | Source node ID |
| `type` | enum | Yes | — | Relationship type (see [Relationship Types](#relationship-types)) |
| `toLabel` | enum | No | — | Filter by target node label |
| `toId` | string | No | — | Filter by target node ID |
| `limit` | integer | No | `100` | Maximum relationships |

```
get_relationships(fromLabel="Application", fromId="order-service", type="CALLS")
```

---

### Mutations

#### `create_incident_ticket`

Create or merge an IncidentTicket node in the topology graph.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Ticket business ID (e.g. `INC-001`) |
| `severity` | enum | Yes | `SEV1`, `SEV2`, `SEV3`, `SEV4` |
| `status` | enum | Yes | `open`, `investigating`, `mitigating`, `resolved` |
| `startTime` | string | No | ISO-8601 timestamp |

```
create_incident_ticket(id="INC-042", severity="SEV2", status="open", startTime="2026-04-05T10:00:00Z")
```

#### `link_incident_to_node`

Create an `IMPACTS` relationship from an IncidentTicket to another topology node.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `fromId` | string | Yes | IncidentTicket business ID |
| `toLabel` | enum | Yes | Target node label |
| `toId` | string | Yes | Target node business ID |

```
link_incident_to_node(fromId="INC-042", toLabel="Application", toId="order-service")
```

#### `update_node_status`

Update the status property of any node.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `label` | enum | Yes | Node label |
| `id` | string | Yes | Node business ID |
| `status` | string | Yes | New status value |

```
update_node_status(label="Anomaly", id="ANO-007", status="resolved")
```

---

## Example Workflow

A typical incident investigation workflow using the tools:

```text
1. list_anomalies(status="active")
   → Find active anomalies in the system

2. root_cause_analysis(startLabel="Anomaly", startId="ANO-007")
   → Traverse downstream to find root cause candidates

3. blast_radius(label="Storage", id="primary-db")
   → Assess how many services are impacted

4. create_incident_ticket(id="INC-042", severity="SEV2", status="investigating")
   → Create an incident ticket

5. link_incident_to_node(fromId="INC-042", toLabel="Storage", toId="primary-db")
   → Link the incident to the affected component

6. update_node_status(label="Anomaly", id="ANO-007", status="resolved")
   → Mark the anomaly as resolved once mitigated
```

## Testing

```bash
# Install dev dependencies
pip install ".[dev]"

# Run the test suite
pytest
```

Tests use [respx](https://github.com/lundberg/respx) to mock HTTP calls to graphserv and cover all 10 tools including parameter validation, error handling, and response formatting.

## Project Structure

```
graphmcpserv/
├── mcp_servers/
│   └── graph_db/
│       └── server.py          # MCP server implementation (all 10 tools)
├── tests/
│   └── test_mcp_graph.py      # Test suite
├── pyproject.toml              # Package configuration
├── Dockerfile                  # Container build
├── .env.example                # Environment variable template
└── README.md
```

## License

See [pyproject.toml](pyproject.toml) for package metadata.
