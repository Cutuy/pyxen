"""a2a_chat client — demonstrates agent-to-agent communication via pyxen.

Loads the pyxen runtime with A2A IPC configured, then sends messages
to a remote agent and prints replies.

Run with (after starting the agent)::

    python -m examples.a2a_chat.client
"""

from __future__ import annotations

import asyncio
import os

from pathlib import Path

from pyxen import Runtime
from pyxen._paths import project_root

HERE = project_root() / "examples" / "a2a_chat"


async def main() -> None:
    rt = await Runtime.load(HERE / "runtime.json")

    print("=== A2A Chat Client ===")
    print(f"Runtime loaded: identity={rt.identity.__class__.__name__}, "
          f"ipc={rt.ipc.__class__.__name__}")
    print()

    # --- request / reply ---

    print("--- send (request/reply) ---")

    reply = await rt.ipc.send("demo-agent", {"action": "echo", "data": "Hello A2A!"})
    print(f"  echo  -> {reply.payload}")

    reply = await rt.ipc.send("demo-agent", {"action": "reverse", "data": "A2A is fun"})
    print(f"  rev   -> {reply.payload}")

    reply = await rt.ipc.send("demo-agent", {"action": "count", "data": "hello world"})
    print(f"  count -> {reply.payload}")

    reply = await rt.ipc.send("demo-agent", {"action": "ping"})
    print(f"  ping  -> {reply.payload}")

    # --- streaming ---

    print()
    print("--- subscribe (streaming) ---")

    async for msg in rt.ipc.subscribe("demo-agent"):
        chunk = msg.payload.get("message", msg.payload)
        idx = msg.payload.get("chunk", "?")
        print(f"  stream chunk {idx}: {chunk}")

    print()
    print("=== done ===")


if __name__ == "__main__":
    if "PYTHONPATH" not in os.environ and (project_root() / "src").is_dir():
        os.environ["PYTHONPATH"] = str(project_root() / "src")
    asyncio.run(main())
