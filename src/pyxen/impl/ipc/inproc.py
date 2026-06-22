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

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        ipc = build({})

        async def test_publish_and_subscribe() -> None:
            received: list[Message] = []

            async def consumer() -> None:
                async for msg in ipc.subscribe("topic-a"):
                    received.append(msg)
                    if len(received) >= 2:
                        return

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0.01)
            await ipc.publish("topic-a", {"hello": "world"})
            await ipc.publish("topic-a", {"goodbye": "world"})
            await asyncio.wait_for(task, timeout=2.0)
            assert len(received) == 2
            assert received[0].payload == {"hello": "world"}
            assert received[0].target == "topic-a"
            assert received[1].payload == {"goodbye": "world"}

        async def test_multiple_subscribers_same_topic() -> None:
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

        async def test_send_returns_synthetic_ack() -> None:
            reply = await ipc.send("agent-x", {"type": "ping"})
            assert reply.target == "agent-x.reply"
            assert reply.payload == {"ack": True}
            assert reply.correlation_id is not None
            assert len(reply.correlation_id) > 0

        async def test_publish_empty_topic() -> None:
            await ipc.publish("nobody-listening", {"x": 1})

        async def test_publish_empty_payload() -> None:
            empty_payload: list[Message] = []

            async def empty_consumer() -> None:
                async for msg in ipc.subscribe("empty-topic"):
                    empty_payload.append(msg)
                    return

            t_empty = asyncio.create_task(empty_consumer())
            await asyncio.sleep(0.01)
            await ipc.publish("empty-topic", {})
            await asyncio.wait_for(t_empty, timeout=2.0)
            assert len(empty_payload) == 1
            assert empty_payload[0].payload == {}

        async def test_publish_unicode() -> None:
            unicode_msgs: list[Message] = []

            async def unicode_consumer() -> None:
                async for msg in ipc.subscribe("unicode-topic"):
                    unicode_msgs.append(msg)
                    return

            t_uni = asyncio.create_task(unicode_consumer())
            await asyncio.sleep(0.01)
            await ipc.publish("unicode-topic", {"emoji": "\U0001f600", "greeting": "\u4f60\u597d"})
            await asyncio.wait_for(t_uni, timeout=2.0)
            assert len(unicode_msgs) == 1
            assert unicode_msgs[0].payload == {"emoji": "\U0001f600", "greeting": "\u4f60\u597d"}

        async def test_multiple_subscribers_fanout() -> None:
            multi_sub_results: list[list[Message]] = [[], [], []]

            async def multi_sub(i: int) -> None:
                async for msg in ipc.subscribe("fanout"):
                    multi_sub_results[i].append(msg)
                    return

            tasks = [asyncio.create_task(multi_sub(i)) for i in range(3)]
            await asyncio.sleep(0.01)
            await ipc.publish("fanout", {"broadcast": True})
            for t in tasks:
                await asyncio.wait_for(t, timeout=2.0)
            for i in range(3):
                assert len(multi_sub_results[i]) == 1
                assert multi_sub_results[i][0].payload == {"broadcast": True}

        await arun_tests(
            test_publish_and_subscribe,
            test_multiple_subscribers_same_topic,
            test_send_returns_synthetic_ack,
            test_publish_empty_topic,
            test_publish_empty_payload,
            test_publish_unicode,
            test_multiple_subscribers_fanout,
        )

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
