---
name: mcp-proxy
description: "Use when: the agent needs external tool access but should not talk to MCP directly, should avoid repeated tool discovery and negotiation, or needs a single compact facade to call MCP while keeping the agent-level protocol hidden. This skill is the agent-facing wrapper: it chooses the correct tool, minimizes parameters, executes one precise call, and returns a compact result without exposing MCP handshake details."
---

# MCP Proxy Agent Facade

This skill is the agent-facing wrapper for external MCP capabilities.

The rule is simple:

- Agent calls this skill
- Skill decides how to use MCP
- Agent never directly negotiates or probes MCP tools
- MCP remains behind a single, compact abstraction layer

## Objective

Turn MCP access into a stable agent interface instead of a raw tool-usage conversation.

The skill should behave like a facade:

1. Receive the task as a high-level intent.
2. Pick the single most relevant MCP tool.
3. Minimize the request payload to the exact needed arguments.
4. Invoke MCP once, without exploratory probing.
5. Return only the final result or the minimal next required fact.

## Required behavior

- Keep all agent-level reasoning at the business-task level.
- Do not ask the agent to explain tool discovery or MCP protocol internals.
- Do not let the agent re-negotiate the same MCP server repeatedly.
- Prefer one precise call over multiple attempts.
- If a required input is missing, ask for only that missing value.
- Return concise, structured output suitable for downstream agent use.

## Anti-patterns

- Do not tell the agent to call MCP tools directly.
- Do not let the agent use broad capability discovery before the real call.
- Do not expose transport / handshake / negotiation logs to the user.
- Do not repeat the same tool lookup in every turn.
- Do not return raw protocol output or verbose tool metadata.

## Execution contract

When this skill is used:

1. Interpret the task as a normal agent request.
2. Choose the relevant MCP tool and server.
3. Construct the smallest valid request.
4. Execute the call once.
5. Return the distilled result, or the single missing fact needed to continue.

## Design principle

This skill is not a workaround for the protocol itself; it is a thin adapter layer.
It reduces token waste and protocol noise by making the agent interact with a stable interface rather than the raw MCP surface.

In other words:

Agent -> Skill -> MCP

not:

Agent -> MCP directly
