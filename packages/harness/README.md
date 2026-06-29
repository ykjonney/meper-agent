# agent-flow-harness

Reusable LangGraph agent harness extracted from the agent-flow backend.
The harness owns the pure agent runtime (state shape, REACT loop, tool
registry, LLM factory); the backend keeps ownership of HTTP, persistence,
auth, and workspace management and adapts the harness to those concerns.
