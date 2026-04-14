# claude-adk-bridge

A2A-compliant bridge that exposes the Claude Agent SDK as an ADK-compatible
agent, enabling Claude-powered agents to run as Kagent BYO agents on Kubernetes.

## Phase 1 (MVP) scope

- Synchronous `message/send` JSON-RPC endpoint
- Agent Card discovery at `/.well-known/agent-card.json`
- Task lookup via `GET /tasks/{id}`
- Health check at `/health`
- In-memory task store (single replica)
- No streaming / memory MCP / OTel / auth yet

## Run locally

```bash
pip install -e '.[dev]'
export ANTHROPIC_API_KEY=sk-...
export AGENT_NAME=my-agent
python -m bridge.main
```

## Run in Docker

```bash
docker build -t claude-adk-bridge:dev .
docker run --rm -p 8080:8080 \
  -e ANTHROPIC_API_KEY=sk-... \
  -e AGENT_NAME=my-agent \
  claude-adk-bridge:dev
```

## Environment variables

See `bridge/config/settings.py` for the full list. Required:
`ANTHROPIC_API_KEY`, `AGENT_NAME`.

## Tests

```bash
pytest -v
```
