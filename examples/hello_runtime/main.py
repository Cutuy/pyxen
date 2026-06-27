"""hello_runtime — the proof-of-life example.

A 30-line Python program that loads the runtime, exercises 3 primitives,
and prints a single line. It does the smallest possible thing that proves
the runtime architecture works end-to-end.

Run with:

    python -m examples.hello_runtime.main

or, from the repo root:

    PYTHONPATH=src python examples/hello_runtime/main.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pyxen import Runtime
from pyxen._paths import project_root

HERE = Path(__file__).resolve().parent


async def main() -> None:
    rt = await Runtime.load(HERE / "runtime.json")

    # 1. Identity — who's calling?
    me = await rt.identity.current()

    # 2. Storage — persist a small record.
    await rt.storage.put("greetings", "world", {"message": "hello, runtime", "from": me.id})
    record = await rt.storage.get("greetings", "world")

    # 3. Observability — emit a single trace.
    async with rt.observability.trace("hello-runtime") as span:
        span.set_attribute("user", me.id)
        span.log("info", "wrote greeting", key="world")

    print(f"hi from {me.id}; storage said: {record}")


if __name__ == "__main__":
    # Allow the example to run from the repo root without installing.
    if "PYTHONPATH" not in os.environ and (project_root() / "src").is_dir():
        os.environ["PYTHONPATH"] = str(project_root() / "src")
    asyncio.run(main())
