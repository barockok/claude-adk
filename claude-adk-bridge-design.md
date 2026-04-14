# Design Document: Claude Agent SDK ↔ ADK Bridge Adapter

**Version:** 0.1  
**Status:** Draft  
**Author:** Barock  
**Purpose:** Technical handoff to Claude Code for implementation

---

## 1. Overview

This document describes the design of a bridge adapter that makes the **Claude Agent SDK** (backed by Claude Code as its runtime) appear as an **ADK-compatible agent** to **Kagent** — a Kubernetes-native AI agent framework.

The goal is to allow teams to deploy Claude-powered agents on Kubernetes using Kagent's existing infrastructure, YAML-based declarative configuration, Kubernetes operator, UI, and observability stack — without Kagent needing to know that Claude is running underneath.

From Kagent's perspective, the agent is just another ADK-compatible pod. Internally, the agent runs Claude Code via the Claude Agent SDK.

---

## 2. Background & Context

### 2.1 Kagent

Kagent is an open-source (Apache 2.0), Kubernetes-native AI agent framework built by Solo.io and now a CNCF Sandbox project. It provides:

- A Kubernetes operator (controller) that watches Agent CRDs and manages their lifecycle
- Declarative YAML-based agent definitions
- Built-in support for MCP tools, multi-agent communication via A2A protocol
- OpenTelemetry-based observability
- A web UI and CLI for managing agents
- Support for multiple LLM providers (Anthropic, OpenAI, Google Vertex AI, Ollama)

Kagent's engine is tightly coupled to **Google ADK** as its agent runtime. It communicates with agents using the **Agent2Agent (A2A) Protocol**.

### 2.2 Claude Agent SDK

The Claude Agent SDK is Anthropic's open-source framework for programmatically building AI agents. It wraps **Claude Code** as its execution runtime, providing:

- Native MCP support via `ClaudeAgentOptions.mcp_servers`
- `PreToolUse` / `PostToolUse` hooks for intercepting agent behavior
- Plugin and skill system via `setting_sources`
- File system, shell, and code execution capabilities built-in
- Python and TypeScript SDKs

### 2.3 The Gap

Kagent natively supports Google ADK agents. It communicates with agents using the **A2A protocol** — a JSON-RPC 2.0 over HTTP(S) standard for agent-to-agent communication. Kagent's controller translates Agent CRDs into ADK-compatible configurations.

Claude Agent SDK does not natively speak A2A. Therefore, a **bridge adapter** is needed to expose Claude Agent SDK as an A2A-compliant HTTP server — making it indistinguishable from an ADK agent from Kagent's perspective.

---

## 3. Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Kubernetes Cluster                     │
│                                                          │
│  ┌────────────────────┐                                  │
│  │  Kagent Controller │  watches Agent CRDs              │
│  │  (Kubernetes Op.)  │  deploys pods                    │
│  └────────┬───────────┘                                  │
│           │ deploys                                       │
│           ▼                                              │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Claude ADK Bridge Container             │ │
│  │                                                      │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │         FastAPI A2A Server (Bridge)           │   │ │
│  │  │  GET /.well-known/agent-card.json             │   │ │
│  │  │  POST /  (message/send, message/stream)       │   │ │
│  │  │  GET /tasks/{id}                              │   │ │
│  │  │  GET /health                                  │   │ │
│  │  └──────────────┬───────────────────────────────┘   │ │
│  │                 │ translates A2A ↔ Claude SDK        │ │
│  │                 ▼                                    │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │           Claude Agent SDK                   │   │ │
│  │  │  ClaudeAgentOptions (tools, MCPs, prompt)    │   │ │
│  │  │  PreToolUse / PostToolUse hooks               │   │ │
│  │  │  Plugins / Skills (setting_sources)           │   │ │
│  │  └──────────────┬───────────────────────────────┘   │ │
│  │                 │                                    │ │
│  │                 ▼                                    │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │           Claude Code (runtime)              │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  │                                                      │ │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │ │
│  │  │ Memory MCP │  │  MCP Tools │  │  OTel Exporter│  │ │
│  │  │(Mem0/custom)│  │ (Slack,    │  │  → Prometheus │  │ │
│  │  │            │  │  GitHub..) │  │               │  │ │
│  │  └────────────┘  └────────────┘  └───────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility |
|---|---|
| **Kagent Controller** | Reads Agent YAML CRDs, manages pod lifecycle, scaling, health |
| **FastAPI A2A Server** | Exposes A2A-compliant HTTP endpoints; translates between A2A protocol and Claude Agent SDK |
| **Claude Agent SDK** | Executes agent logic; manages tool calls, hooks, and plugins |
| **Claude Code (runtime)** | Low-level execution engine bundled inside the container |
| **Memory MCP Server** | Provides persistent memory across sessions (replaces ADK MemoryService) |
| **MCP Tool Servers** | External integrations (Slack, GitHub, alerting, etc.) |
| **OTel Exporter** | Emits metrics (token usage, task duration, tool calls) to Prometheus/Grafana |

---

## 4. A2A Protocol Implementation

### 4.1 Required Endpoints

The bridge must implement the following A2A-compliant endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/agent-card.json` | GET | Agent discovery — returns Agent Card JSON |
| `/` | POST | `message/send` — synchronous request/response |
| `/` | POST | `message/stream` — streaming via SSE (when `streaming: true`) |
| `/tasks/{task_id}` | GET | `tasks/get` — poll task status |
| `/health` | GET | Kubernetes liveness/readiness probe |

### 4.2 Agent Card

The Agent Card is generated dynamically from the agent's YAML configuration at startup.

```json
{
  "name": "my-claude-agent",
  "description": "A Claude-powered agent deployed on Kubernetes",
  "url": "http://my-claude-agent.kagent.svc.cluster.local",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "skills": [
    {
      "id": "code-execution",
      "name": "Code Execution",
      "description": "Can read, write, and execute code"
    }
  ],
  "authentication": {
    "schemes": ["Bearer"]
  }
}
```

### 4.3 Task Lifecycle Mapping

A2A defines a task lifecycle that must be mapped from Claude Agent SDK's streaming output:

```
A2A Task State         Claude Agent SDK Event
─────────────────      ──────────────────────────────
submitted          →   Task created, queued for processing
working            →   Claude is actively generating / using tools
input_required     →   Claude emits AskUserQuestion (human-in-the-loop)
completed          →   Claude emits ResultMessage
failed             →   Exception raised in Claude SDK query()
canceled           →   Client sends cancel request
```

### 4.4 Message Flow

**Synchronous (`message/send`):**
```
Client → POST / (JSON-RPC message/send)
       → Extract prompt from message parts
       → Call claude_agent_sdk.query(prompt, options)
       → Collect all output messages
       → Return Task object with final result
```

**Streaming (`message/stream`):**
```
Client → POST / (JSON-RPC message/stream)
       → Extract prompt
       → Call claude_agent_sdk.query(prompt, options) as async iterator
       → For each message chunk:
           → Emit SSE: TaskStatusUpdateEvent (working)
           → Emit SSE: TaskArtifactUpdateEvent (content chunk)
       → Emit SSE: TaskStatusUpdateEvent (completed)
       → Close SSE stream
```

---

## 5. ADK Feature Mapping

The following table shows how each ADK feature maps to the Claude Agent SDK equivalent in this bridge:

| ADK Feature | ADK Implementation | Bridge Implementation |
|---|---|---|
| **Short-term memory (session state)** | `session.state` key-value store via `ToolContext` | Redis-backed MCP server exposing `get_state` / `set_state` tools |
| **Long-term memory** | `VertexAIMemoryBankService` / `InMemoryMemoryService` | Mem0 or custom vector-backed MCP server exposing `search_memory` / `save_memory` |
| **Memory ingestion (after turn)** | `after_agent` callback → `add_session_to_memory` | `PostToolUse` hook → call memory MCP `save_memory` |
| **Tools / Skills** | ADK `ToolSet`, function tools | Claude Agent SDK `allowed_tools`, plugins, `setting_sources` |
| **MCP servers** | `McpToolset` | `ClaudeAgentOptions.mcp_servers` (both in-process and remote) |
| **Hooks / Callbacks** | `before_tool_call`, `after_tool_call` callbacks | `PreToolUse`, `PostToolUse` hooks |
| **Telemetry / Tracing** | Native OpenTelemetry in ADK | OTel via hooks; emit spans on tool calls |
| **Multi-agent (A2A)** | Native A2A Agent Cards | FastAPI A2A server (this bridge) |
| **System prompt** | `agent.instruction` | `ClaudeAgentOptions.system_prompt` |
| **Model config** | `LlmAgent(model=...)` | `ClaudeAgentOptions.model` |
| **Streaming** | Native SSE via ADK runner | Translate Claude SDK async iterator → SSE |

---

## 6. Agent YAML Configuration

Kagent Agent CRDs are extended to support Claude-specific configuration. The bridge reads these values at startup from environment variables or a mounted ConfigMap.

### 6.1 Example Agent YAML

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: my-claude-agent
  namespace: kagent
spec:
  description: "A Claude-powered SRE agent"
  type: BYO
  byo:
    deployment:
      image: my-org/claude-adk-bridge:latest
      env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: anthropic-secret
              key: api_key
        - name: AGENT_SYSTEM_PROMPT
          value: "You are an SRE agent. Help diagnose and fix Kubernetes issues."
        - name: AGENT_MODEL
          value: "claude-sonnet-4-6"
        - name: AGENT_MAX_TURNS
          value: "20"
        - name: AGENT_ALLOWED_TOOLS
          value: "Bash,Read,Write,Edit"
        - name: MEMORY_MCP_URL
          value: "http://memory-service.kagent.svc:8080/mcp"
        - name: MCP_SERVERS
          value: |
            {
              "slack": {"url": "https://mcp.slack.com/mcp"},
              "github": {"url": "https://github.mcp.example.com/mcp"}
            }
      ports:
        - containerPort: 8080
      livenessProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 10
        periodSeconds: 30
      readinessProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 5
        periodSeconds: 10
  modelConfig:
    name: anthropic-config
```

---

## 7. Project Structure

```
claude-adk-bridge/
├── Dockerfile
├── pyproject.toml
├── README.md
│
├── bridge/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   │
│   ├── a2a/
│   │   ├── __init__.py
│   │   ├── server.py            # A2A HTTP endpoint handlers
│   │   ├── agent_card.py        # Agent Card generation from config
│   │   ├── models.py            # A2A protocol Pydantic models
│   │   ├── task_manager.py      # Task lifecycle state management
│   │   └── sse.py               # SSE streaming utilities
│   │
│   ├── claude/
│   │   ├── __init__.py
│   │   ├── runner.py            # Claude Agent SDK invocation
│   │   ├── options.py           # ClaudeAgentOptions builder from config
│   │   ├── hooks.py             # PreToolUse / PostToolUse hooks
│   │   └── stream_adapter.py   # Claude stream → A2A SSE translator
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── mcp_memory.py        # Memory MCP server (short + long term)
│   │   └── session_store.py     # Redis-backed session state
│   │
│   ├── telemetry/
│   │   ├── __init__.py
│   │   ├── otel.py              # OpenTelemetry setup
│   │   └── metrics.py           # Token usage, task duration, tool call metrics
│   │
│   └── config/
│       ├── __init__.py
│       └── settings.py          # Pydantic settings from env vars
│
└── tests/
    ├── test_a2a_server.py
    ├── test_claude_runner.py
    ├── test_memory.py
    └── test_stream_adapter.py
```

---

## 8. Key Implementation Details

### 8.1 FastAPI A2A Server (`bridge/a2a/server.py`)

```python
# Pseudocode — implement this in bridge/a2a/server.py

POST /
  body: JSON-RPC 2.0 Request
  if method == "message/send":
      prompt = extract_prompt(body.params.message)
      result = await claude_runner.run(prompt)
      return jsonrpc_response(task_to_a2a(result))

  if method == "message/stream":
      prompt = extract_prompt(body.params.message)
      return StreamingResponse(
          stream_claude_to_sse(prompt),
          media_type="text/event-stream"
      )

GET /.well-known/agent-card.json
  return AgentCard generated from settings

GET /tasks/{task_id}
  return task_manager.get(task_id)

GET /health
  return {"status": "ok"}
```

### 8.2 Claude Runner (`bridge/claude/runner.py`)

```python
# Pseudocode — implement this in bridge/claude/runner.py

async def run(prompt: str) -> ClaudeResult:
    options = build_options_from_config()  # from env vars
    messages = []
    async for message in query(prompt=prompt, options=options):
        messages.append(message)
    return messages

async def stream(prompt: str) -> AsyncIterator[ClaudeMessage]:
    options = build_options_from_config()
    async for message in query(prompt=prompt, options=options):
        yield message
```

### 8.3 Stream Adapter (`bridge/claude/stream_adapter.py`)

```python
# Pseudocode — implement this in bridge/claude/stream_adapter.py

async def stream_claude_to_sse(prompt: str) -> AsyncIterator[str]:
    task_id = generate_task_id()

    # Emit: task submitted
    yield sse_event(TaskStatusUpdateEvent(task_id, status="submitted"))
    # Emit: task working
    yield sse_event(TaskStatusUpdateEvent(task_id, status="working"))

    async for message in claude_runner.stream(prompt):
        if is_text_chunk(message):
            yield sse_event(TaskArtifactUpdateEvent(task_id, content=message.text))
        elif is_tool_use(message):
            yield sse_event(TaskStatusUpdateEvent(task_id, status="working",
                            detail=f"Using tool: {message.tool_name}"))

    # Emit: task completed
    yield sse_event(TaskStatusUpdateEvent(task_id, status="completed"))
```

### 8.4 Memory MCP Server (`bridge/memory/mcp_memory.py`)

```python
# Pseudocode — implement this in bridge/memory/mcp_memory.py
# Exposes memory as MCP tools that Claude can call natively

@tool("get_state", "Get a value from session state", {"key": str})
async def get_state(args):
    value = await redis.get(f"session:{session_id}:{args['key']}")
    return {"value": value}

@tool("set_state", "Set a value in session state", {"key": str, "value": str})
async def set_state(args):
    await redis.set(f"session:{session_id}:{args['key']}", args["value"])
    return {"status": "ok"}

@tool("search_memory", "Search long-term memory", {"query": str})
async def search_memory(args):
    results = await vector_store.search(args["query"])
    return {"memories": results}

@tool("save_memory", "Save to long-term memory", {"content": str})
async def save_memory(args):
    await vector_store.insert(args["content"])
    return {"status": "ok"}
```

### 8.5 Hooks & Telemetry (`bridge/claude/hooks.py`)

```python
# Pseudocode — implement this in bridge/claude/hooks.py

async def pre_tool_use(input: PreToolUseInput):
    # Start OTel span for tool call
    span = tracer.start_span(f"tool.{input.tool_name}")
    context.set("current_span", span)
    return {"allow": True}

async def post_tool_use(input: PostToolUseInput):
    # End OTel span
    span = context.get("current_span")
    span.set_attribute("tool.name", input.tool_name)
    span.end()

    # Emit Prometheus metrics
    tool_call_counter.inc(labels={"tool": input.tool_name})

    # Trigger memory ingestion after turn if memory MCP configured
    if is_last_turn(input) and memory_mcp_enabled():
        await memory_mcp.save_memory(summarize_turn(input))
```

---

## 9. Telemetry & Metrics

The bridge emits the following metrics via OpenTelemetry → Prometheus:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `claude_agent_tokens_total` | Counter | `agent_name`, `type` (input/output) | Total tokens consumed |
| `claude_agent_task_duration_seconds` | Histogram | `agent_name`, `status` | Task processing time |
| `claude_agent_tool_calls_total` | Counter | `agent_name`, `tool_name` | Tool invocations |
| `claude_agent_tasks_total` | Counter | `agent_name`, `status` | Task completions by status |
| `claude_agent_memory_operations_total` | Counter | `agent_name`, `operation` | Memory read/write ops |

---

## 10. Environment Variables

The bridge is configured entirely via environment variables, suitable for Kubernetes secrets and ConfigMaps.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `AGENT_NAME` | Yes | — | Agent name (used in Agent Card) |
| `AGENT_DESCRIPTION` | No | `""` | Agent description |
| `AGENT_SYSTEM_PROMPT` | No | `""` | System prompt for Claude |
| `AGENT_MODEL` | No | `claude-sonnet-4-6` | Claude model to use |
| `AGENT_MAX_TURNS` | No | `10` | Max turns per task |
| `AGENT_ALLOWED_TOOLS` | No | `Read,Bash` | Comma-separated allowed tools |
| `MCP_SERVERS` | No | `{}` | JSON map of MCP server configs |
| `MEMORY_MCP_URL` | No | `""` | URL for external memory MCP server |
| `MEMORY_BACKEND` | No | `redis` | Memory backend: `redis` or `in-memory` |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis URL for session state |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `""` | OpenTelemetry collector endpoint |
| `BRIDGE_PORT` | No | `8080` | HTTP server port |
| `BRIDGE_HOST` | No | `0.0.0.0` | HTTP server bind host |
| `SKILLS_DIR` | No | `/app/skills` | Directory for Claude skill files |

---

## 11. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Node.js (required for Claude Code CLI)
RUN apt-get update && apt-get install -y nodejs npm curl && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (bundled with claude-agent-sdk but explicit for clarity)
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
COPY pyproject.toml .
RUN pip install -e .

# Copy application code
COPY bridge/ bridge/

# Optional: mount skills at runtime via ConfigMap/volume
RUN mkdir -p /app/skills

# Health check
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["python", "-m", "bridge.main"]
```

---

## 12. Python Dependencies (`pyproject.toml`)

```toml
[project]
name = "claude-adk-bridge"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "claude-agent-sdk>=0.2.0",         # Claude Agent SDK
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "redis>=5.0.0",                     # Session state backend
    "opentelemetry-sdk>=1.25.0",        # Telemetry
    "opentelemetry-exporter-otlp>=1.25.0",
    "prometheus-client>=0.20.0",
    "httpx>=0.27.0",                    # Async HTTP client
    "anyio>=4.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]
```

---

## 13. Implementation Phases

### Phase 1 — Core Bridge (MVP)
- FastAPI A2A server with `message/send` (synchronous)
- Agent Card generation from env vars
- Claude Agent SDK invocation
- `/health` endpoint
- Basic Dockerfile
- Deploy as BYO agent in Kagent

### Phase 2 — Streaming & Memory
- SSE streaming for `message/stream`
- `tasks/get` polling endpoint
- In-process memory MCP server (in-memory backend)
- Redis-backed session state

### Phase 3 — Telemetry & Hooks
- `PreToolUse` / `PostToolUse` hooks
- OpenTelemetry spans per tool call
- Prometheus metrics endpoint
- Grafana dashboard definition (optional)

### Phase 4 — Production Hardening
- Long-term memory with vector store backend (Mem0 / Chroma)
- Skills directory mount from Kubernetes ConfigMap
- External MCP server wiring from YAML config
- Auth (Bearer token on A2A endpoints)
- Helm chart for easy deployment

---

## 14. Testing Strategy

| Test Type | What to Test |
|---|---|
| Unit | A2A model serialization, Agent Card generation, task state machine |
| Integration | Full `message/send` round-trip with mock Claude SDK |
| Integration | SSE streaming correctness |
| Integration | Memory MCP tool calls |
| E2E | Deploy bridge in Kind cluster + Kagent, send task, verify response |

---

## 15. Open Questions

1. **A2A version** — Kagent currently uses its own internal A2A variant. Verify exact JSON-RPC method names (`message/send` vs `tasks/send`) against the Kagent source before finalizing endpoint signatures.
2. **Claude Code licensing** — Confirm Anthropic's terms allow bundling Claude Code binary inside a redistributable container image.
3. **Memory backend** — For MVP, in-memory is fine. Decide on Redis vs Postgres for production session state before Phase 2.
4. **Skills packaging** — Decide whether skills are baked into the image or mounted via Kubernetes ConfigMap at runtime.
5. **Multi-tenancy** — Decide if one bridge container = one agent, or if one container can serve multiple agents with different configs.

---

## 16. References

- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Kagent GitHub](https://github.com/kagent-dev/kagent)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Kagent Architecture Docs](https://kagent.dev/docs/kagent/concepts/architecture)
- [Kagent BYO Agent Guide](https://www.cloudnativedeepdive.com/running-any-ai-agent-on-kubernetes-step-by-step/)
