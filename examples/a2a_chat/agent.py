"""a2a_chat agent — a minimal A2A protocol server.

Runs an A2A-compatible agent that processes tasks sent via JSON-RPC.
Supports both request/reply (``tasks/sendMessage``) and streaming
(``tasks/sendStreamingMessage``) interaction patterns.

Run with::

    uvicorn examples.a2a_chat.agent:app --reload --port 8080

or::

    python -m examples.a2a_chat.agent
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

app = FastAPI(
    title="pyxen A2A demo agent",
    version="0.1.0",
    description="Demonstrates the Agent-to-Agent protocol for pyxen.",
)

AGENT_CARD: dict[str, Any] = {
    "name": "pyxen-demo-agent",
    "description": "A demonstration A2A agent for the pyxen runtime",
    "url": "http://localhost:8080/",
    "capabilities": {
        "streaming": True,
    },
}

# In-memory task store for poll-based retrieval
_tasks: dict[str, dict[str, Any]] = {}


def _process_task(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a task and return the completed task object."""
    task_id: str = params.get("id", str(uuid.uuid4()))
    message: dict[str, Any] = params.get("message", {})
    parts: list[dict[str, Any]] = message.get("parts", [])

    payload: dict[str, Any] = {}
    for part in parts:
        if part.get("type") == "text":
            try:
                payload = json.loads(part["text"])
            except (json.JSONDecodeError, TypeError):
                payload = {"text": part.get("text", "")}

    action: str = payload.get("action", "echo")
    data: str = str(payload.get("data", payload.get("text", "")))

    if action == "echo":
        reply: dict[str, Any] = {"action": "echo", "data": data, "reply": f"Echo: {data}"}
    elif action == "reverse":
        reply = {"action": "reverse", "data": data, "reply": data[::-1]}
    elif action == "ping":
        reply = {"action": "pong", "data": "ping"}
    elif action == "count":
        count = int(data) if data.isdigit() else len(data)
        reply = {"action": "count", "data": data, "reply": f"Count: {count}"}
    else:
        reply = {
            "action": action,
            "data": data,
            "reply": f"Hello from pyxen A2A agent! You said: {data}",
        }

    task: dict[str, Any] = {
        "id": task_id,
        "status": {"state": "completed"},
        "artifacts": [
            {
                "parts": [{"type": "text", "text": json.dumps(reply)}],
            }
        ],
    }
    _tasks[task_id] = task
    return task


async def _stream_task(params: dict[str, Any]) -> AsyncGenerator[str, None]:
    """Stream task artifacts via SSE, then signal completion."""
    task_id: str = params.get("id", str(uuid.uuid4()))
    message: dict[str, Any] = params.get("message", {})
    parts: list[dict[str, Any]] = message.get("parts", [])

    payload: dict[str, Any] = {}
    for part in parts:
        if part.get("type") == "text":
            try:
                payload = json.loads(part["text"])
            except (json.JSONDecodeError, TypeError):
                payload = {"text": part.get("text", "")}

    action: str = payload.get("action", "echo")
    data: str = str(payload.get("data", payload.get("text", "")))
    topic: str = str(payload.get("topic", ""))

    chunks: list[str] = []
    if topic:
        chunks = [
            f"Connected to agent '{topic}'",
            "Available actions: echo, reverse, count, ping",
            'Try: rt.ipc.send("demo-agent", {"action": "echo", "data": "hi"})',
        ]
    elif action == "echo":
        chunks = [f"Echo: {data}"]
    elif action == "reverse":
        for ch in data[::-1]:
            chunks.append(f"char: {ch}")
    elif action == "count":
        chunks = ["Processing...", f"Count is {len(data)}"]
    else:
        chunks = ["Hello from pyxen A2A!", f"You said: {data}"]
        if len(data) > 3:
            chunks.append(f"Your message was {len(data)} characters long")

    for i, chunk in enumerate(chunks):
        await asyncio.sleep(0.3)
        artifact: dict[str, Any] = {
            "id": task_id,
            "artifacts": [
                {
                    "parts": [{"type": "text", "text": json.dumps({"chunk": i, "message": chunk})}],
                }
            ],
        }
        yield f"event: task_artifact_update\ndata: {json.dumps({'result': artifact})}\n\n"

    status: dict[str, Any] = {"id": task_id, "status": {"state": "completed"}}
    yield f"event: task_status_update\ndata: {json.dumps({'result': status})}\n\n"


@app.get("/.well-known/agent-card.json")
async def well_known_card() -> JSONResponse:
    """A2A agent card discovery endpoint."""
    return JSONResponse(AGENT_CARD)


@app.post("/", response_model=None)
async def jsonrpc_handler(request: Request) -> Response:
    """Single endpoint handling all A2A JSON-RPC methods."""
    body: dict[str, Any] = await request.json()
    method: str | None = body.get("method")
    params: dict[str, Any] = body.get("params", {})
    req_id: int | str | None = body.get("id")

    if method == "tasks/sendMessage":
        task = _process_task(params)
        return JSONResponse({"jsonrpc": "2.0", "result": task, "id": req_id})

    if method == "tasks/sendStreamingMessage":
        return StreamingResponse(
            _stream_task(params),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    if method == "tasks/get":
        task_id: str = str(params.get("id", ""))
        existing = _tasks.get(task_id)
        t: dict[str, Any] = existing if existing is not None else {"id": task_id, "status": {"state": "completed"}, "artifacts": []}
        return JSONResponse({"jsonrpc": "2.0", "result": t, "id": req_id})

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": req_id,
        },
        status_code=400,
    )


def _main() -> None:
    """Run the agent server directly."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    _main()
