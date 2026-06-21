# a2a_chat — Agent-to-Agent communication example

Demonstrates A2A protocol interaction using pyxen's `A2AIpc` implementation.

## Architecture

```
┌──────────────┐    JSON-RPC 2.0     ┌──────────────────┐
│  client.py   │ ──── HTTP/SSE ────▶ │  agent.py         │
│  (pyxen A2A) │ ◀────────────────── │  (FastAPI server) │
└──────────────┘                     └──────────────────┘
     │                                       │
  Runtime.load("runtime.json")          /.well-known/
     │                                  agent-card.json
  rt.ipc.send("demo-agent", ...)        POST / (JSON-RPC)
  rt.ipc.subscribe("demo-agent")        POST / (SSE stream)
```

## Prerequisites

```bash
pip install pyxen[a2a]       # A2A client (httpx + httpx-sse)
pip install pyxen[examples]  # FastAPI + uvicorn for the server
```

Or install everything at once:

```bash
pip install pyxen[a2a,examples]
```

## Run

**Terminal 1 — Start the agent:**

```bash
python -m examples.a2a_chat.agent
# or: uvicorn examples.a2a_chat.agent:app --port 8080
```

The agent listens on `http://localhost:8080/` and serves its agent card
at `http://localhost:8080/.well-known/agent-card.json`.

**Terminal 2 — Run the client:**

```bash
PYTHONPATH=src python examples/a2a_chat/client.py
```

Expected output:

```
=== A2A Chat Client ===
Runtime loaded: identity=EnvIdentity, ipc=A2AIpc

--- send (request/reply) ---
  echo  -> {'action': 'echo', 'data': 'Hello A2A!', 'reply': 'Echo: Hello A2A!'}
  rev   -> {'action': 'reverse', 'data': 'A2A is fun', 'reply': 'nuf si A2A'}
  count -> {'action': 'count', 'data': 'hello world', 'reply': 'Count: 11'}
  ping  -> {'action': 'pong', 'data': 'ping'}

--- subscribe (streaming) ---
  stream chunk 0: Hello from pyxen A2A!
  stream chunk 1: You said: demo-agent
  stream chunk 2: Your message was 11 characters long

=== done ===
```

## What's happening

1. `client.py` loads the runtime from `runtime.json`, which configures the
   `a2a` IPC implementation with `demo-agent` pointing at `localhost:8080`.
2. `rt.ipc.send("demo-agent", ...)` sends a **JSON-RPC 2.0** `tasks/sendMessage`
   request to the agent. The agent processes it and returns a completed task
   with the result in an artifact part.
3. `rt.ipc.subscribe("demo-agent")` sends a `tasks/sendStreamingMessage`
   request. The agent streams back artifacts via **Server-Sent Events (SSE)**
   before signalling completion.

No external dependencies, API keys, or LLM calls are required — the agent
runs entirely locally.
