# agent-flow-harness

A reusable LangGraph agent runtime. The harness owns the pure agent
execution (state shape, REACT loop via node graph, tool registry, LLM
factory, context engineering, guards, middleware) and stays decoupled
from HTTP, persistence, auth, and workspace storage — callers inject
every external dependency.

## Quick Start

```python
from agent_flow_harness import AgentConfig, create_agent
from langchain_openai import ChatOpenAI

# 1. Build your LLM (the harness never constructs it for you)
model = ChatOpenAI(model="gpt-4o", api_key="sk-...")

# 2. Configure the agent
config = AgentConfig(
    name="my-agent",
    system_prompt="You are a helpful assistant.",
)

# 3. Create & run
agent = create_agent(config, model)

# Non-streaming
result = await agent.run("Hello!")
print(result)

# Streaming (receives AppEvent dicts)
async def on_event(event: dict):
    print(event["type"], event.get("content", ""))

await agent.stream("Tell me a joke", on_event=on_event)
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Your Application                                    │
│                                                      │
│  ┌─────────────┐    ┌──────────────────────────┐   │
│  │ API / CLI   │───▶│ Integration Adapter      │   │
│  │             │    │ (you write this)         │   │
│  └─────────────┘    └──────────┬───────────────┘   │
│                                │                     │
│                                │ inject              │
│                                ▼                     │
│                    ┌──────────────────────┐         │
│                    │  agent_flow_harness   │         │
│                    │                      │         │
│                    │  create_agent()       │         │
│                    │  build_agent_graph()  │         │
│                    │  stream/invoke/resume │         │
│                    └──────────────────────┘         │
└─────────────────────────────────────────────────────┘
```

The harness is a **library**, not a framework. It does not run a server,
manage routes, or own your database. You call it, it runs the agent,
and returns results.

## What You Inject

The harness never touches your credentials, database, or filesystem.
Everything external is injected:

| Dependency | Required? | How |
|---|---|---|
| **LLM** (`BaseChatModel`) | Yes | `create_agent(config, model=...)` |
| **Tools** | No | `AgentConfig.tools` or pass at build time |
| **Checkpointer** | No (defaults to MemorySaver) | `configure_checkpointer(saver)` at startup |
| **Sandbox** | No | `AgentConfig.sandbox=DockerSandbox(...)` |
| **Workspace** | No | `agent.run(input, workspace=...)` |
| **Guards** | No | `AgentConfig.guards=[TimeBudgetGuard(60)]` |
| **Middleware** | No | `AgentConfig.middleware=[AuditMiddleware()]` |

## High-Level API (recommended)

```python
from agent_flow_harness import AgentConfig, create_agent

config = AgentConfig(
    name="researcher",
    system_prompt="You are a research assistant.",
    tools=[{"name": "bash"}, {"name": "read"}, {"name": "grep"}],
    guards=[{"type": "time_budget", "max_seconds": 120}],
)
agent = create_agent(config, model)
```

`Agent` exposes `.run()`, `.stream()`, `.get_history()`.

## Low-Level API (escape hatch)

When you need full control over graph construction:

```python
from agent_flow_harness import build_agent_graph, build_config, run_agent

graph = build_agent_graph(agent_doc, checkpointer=saver)
config = build_config(agent_doc, llm, tools=tools, thread_id="session-1")
result = await run_agent(graph, input_state, config=config)
```

## Built-in Tools

| Tool | Description |
|---|---|
| `bash` | Execute shell commands (delegates to Sandbox) |
| `read` / `write` | File I/O (via Sandbox) |
| `glob` / `grep` | File search (via Sandbox) |
| `ask_clarification` | Pause execution and ask the user a question (interrupt) |
| `delegate_to_subagent` | Delegate a subtask to another agent |
| `tool_search` | Search for available tools dynamically |

## Event System

The streaming adapter translates LangGraph events into 9 app-layer
event types:

| Event | When |
|---|---|
| `text_delta` | LLM token stream |
| `text` | Complete text block |
| `thinking_delta` / `thinking` | Reasoning (when enabled) |
| `tool_call_start` / `tool_call` / `tool_result` | Tool execution |
| `interrupt` | Agent paused (ask_clarification) |
| `error` | Execution error |

## Checkpointer

The harness ships with a default in-memory checkpointer
(`MemorySaver`). For production, inject a durable backend:

```python
from agent_flow_harness import build_mongo_saver, configure_checkpointer

saver = build_mongo_saver(client=mongo_client, db_name="my_db")
configure_checkpointer(saver, overwrite=True)
```

The checkpointer powers:
- **Multi-turn context**: thread history persists across requests
- **Compression**: compressed context is cached, not recomputed
- **Interrupt/Resume**: `ask_clarification` pauses mid-execution

## Writing Your Own Adapter

The harness is backend-agnostic. To embed it in your application:

1. **Build the LLM** from your config (model table, env vars, etc.)
2. **Resolve tools** (your skill system, MCP connections, custom tools)
3. **Configure checkpointer** (MongoDB, Postgres, or memory)
4. **Call** `build_agent_graph` + `build_config` + `run_agent` / `astream_events`

See `backend/app/engine/harness_integration/` for a complete reference
implementation (the agent-flow backend's adapter).
