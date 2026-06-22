"""IPC primitive — inter-process or inter-agent messaging.

The runtime's IPC abstraction is a generic message-bus interface. The same
interface can be backed by:
  - in-process queues (single process, multiple coroutines)
  - Unix sockets (local)
  - NATS / Redis Pub-Sub / SQS (network)
  - OpenAI Agents SDK handoffs (when agents are involved)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Message:
    """A message sent to or received from another process/agent."""

    target: str
    payload: dict[str, Any]
    correlation_id: str | None = None


class IpcImpl(Protocol):
    """Implementation protocol for the ipc primitive."""

    async def send(self, target: str, payload: dict[str, Any]) -> Message:
        """Send a message to ``target`` and await a reply (request/reply)."""
        ...

    def subscribe(self, topic: str) -> AsyncIterator[Message]:
        """Subscribe to a stream of messages on ``topic``."""
        ...

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget publish to ``topic``."""
        ...


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_message_required_fields() -> None:
        m = Message(target="agent-a", payload={"type": "ping"})
        assert m.target == "agent-a"
        assert m.payload == {"type": "ping"}
        assert m.correlation_id is None

    def test_message_with_correlation_id() -> None:
        m2 = Message(target="agent-b", payload={"x": 1}, correlation_id="abc-123")
        assert m2.correlation_id == "abc-123"
        assert m2.payload == {"x": 1}

    def test_message_empty_payload() -> None:
        m3 = Message(target="t", payload={})
        assert m3.payload == {}

    def test_message_frozen() -> None:
        m = Message(target="agent-a", payload={"type": "ping"})
        try:
            m.target = "mutate"  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            pass
        else:
            raise AssertionError("Message should be frozen")

    run_tests(
        test_message_required_fields,
        test_message_with_correlation_id,
        test_message_empty_payload,
        test_message_frozen,
    )


if __name__ == "__main__":
    _main()
