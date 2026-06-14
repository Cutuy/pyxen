"""``inproc`` ipc impl — async in-process message bus.

For single-process apps and tests. Topics are asyncio queues keyed by
topic name. ``send`` is a request/reply pattern: the publisher awaits a
reply on a one-shot queue.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ...core.ipc import Message


class InProcIpc:
    """In-process pub/sub + request/reply. No persistence, no cross-process."""

    def __init__(self, config: dict[str, object]) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Message]]] = {}
        self._lock = asyncio.Lock()

    async def _get_queue(self, topic: str) -> asyncio.Queue[Message]:
        async with self._lock:
            queue = self._subscribers.get(topic)
            if queue is None:
                queue = []
                self._subscribers[topic] = queue
            q: asyncio.Queue[Message] = asyncio.Queue()
            queue.append(q)
            return q

    async def send(self, target: str, payload: dict[str, Any]) -> Message:
        correlation_id = str(uuid.uuid4())
        # In-process send is fire-and-forget for MVP: publish to the target
        # topic and return a synthetic ack.
        await self.publish(target, payload)
        return Message(target=f"{target}.reply", payload={"ack": True}, correlation_id=correlation_id)

    async def subscribe(self, topic: str) -> AsyncIterator[Message]:
        queue = await self._get_queue(topic)
        while True:
            msg = await queue.get()
            yield msg

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(topic, []))
        for queue in queues:
            await queue.put(Message(target=topic, payload=payload))


def build(config: dict[str, object]) -> InProcIpc:
    return InProcIpc(config)


def _main() -> None:
    """Test entry point for inproc ipc impl."""
    import asyncio

    async def go() -> None:
        ipc = build({})

        # publish + subscribe
        received: list[Message] = []

        async def consumer() -> None:
            async for msg in ipc.subscribe("topic-a"):
                received.append(msg)
                if len(received) >= 2:
                    return

        task = asyncio.create_task(consumer())
        # Yield so the subscriber registers before publishing
        await asyncio.sleep(0.01)
        await ipc.publish("topic-a", {"hello": "world"})
        await ipc.publish("topic-a", {"goodbye": "world"})
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0].payload == {"hello": "world"}
        assert received[0].target == "topic-a"
        assert received[1].payload == {"goodbye": "world"}

        # Multiple subscribers on the same topic
        sub1: list[Message] = []
        sub2: list[Message] = []

        async def c1() -> None:
            async for msg in ipc.subscribe("multi"):
                sub1.append(msg)
                return

        async def c2() -> None:
            async for msg in ipc.subscribe("multi"):
                sub2.append(msg)
                return

        t1 = asyncio.create_task(c1())
        t2 = asyncio.create_task(c2())
        await asyncio.sleep(0.01)
        await ipc.publish("multi", {"x": 1})
        await asyncio.wait_for(t1, timeout=2.0)
        await asyncio.wait_for(t2, timeout=2.0)
        assert len(sub1) == 1
        assert len(sub2) == 1

        # send returns synthetic ack
        reply = await ipc.send("agent-x", {"type": "ping"})
        assert reply.target == "agent-x.reply"
        assert reply.payload == {"ack": True}
        assert reply.correlation_id is not None
        assert len(reply.correlation_id) > 0  # uuid

        # publish on empty topic is a no-op
        await ipc.publish("nobody-listening", {"x": 1})  # should not raise

    asyncio.run(go())


if __name__ == "__main__":
    _main()
