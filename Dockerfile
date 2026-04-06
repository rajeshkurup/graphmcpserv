FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY mcp_servers/ mcp_servers/

RUN pip install --no-cache-dir .

ENV GRAPHSERV_URL=http://graphserv:8080
ENV GRAPHSERV_TIMEOUT=10.0

CMD ["python", "-m", "mcp_servers.graph_db.server"]
