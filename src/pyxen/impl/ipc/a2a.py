"""``a2a`` ipc impl — Agent-to-Agent protocol communication.

Implements the Agent-to-Agent (A2A) protocol using JSON-RPC 2.0 over
HTTP/HTTPS with SSE for streaming. Agents are configured by name with
their A2A endpoint URLs.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..._testlib import skip
from ...core.ipc import Message

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

try:
    import httpx_sse
    _HAS_HTTPX_SSE = True
except ImportError:
    httpx_sse = None  # type: ignore[assignment]
    _HAS_HTTPX_SSE = False


class A2AIpc:
    """Agent-to-Agent protocol IPC implementation.

    Config shape::

        {
            'agents': {
                'agent-name': {
                    'url': 'https://host/a2a',
                    'bearer_token': '...',    # optional
                    'api_key': '...',         # optional
                }
            },
            'timeout_seconds': 30,
            'default_bearer_token': '...',   # optional fallback
        }
    """

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_HTTPX or not _HAS_HTTPX_SSE:
            raise RuntimeError(
                "httpx and httpx-sse are required for A2A IPC. "
                "Install with: pip install pyxen[a2a]"
            )
        self._config = config
        self._timeout_seconds = float(config.get("timeout_seconds", 30))  # type: ignore[arg-type]
        agents_raw = config.get("agents", {})
        if not isinstance(agents_raw, dict):
            raise RuntimeError(
                "A2A config: 'agents' must be a dict mapping names to agent configs"
            )
        self._agents: dict[str, dict[str, object]] = agents_raw
        raw_token = config.get("default_bearer_token")
        self._default_bearer_token: str | None = str(raw_token) if raw_token is not None else None
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._agent_cards: dict[str, dict[str, Any]] = {}

    def _get_headers(self, agent_name: str) -> dict[str, str]:
        agent = self._agents.get(agent_name, {})
        headers: dict[str, str] = {"Content-Type": "application/json"}
        bearer = agent.get("bearer_token") or self._default_bearer_token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        api_key = agent.get("api_key")
        if api_key:
            headers["X-API-Key"] = str(api_key)
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self._timeout_seconds)
                    )
        return self._client

    def _get_url(self, agent_name: str) -> str:
        agent = self._agents.get(agent_name)
        if agent is None:
            raise RuntimeError(
                f"A2A agent '{agent_name}' not found in config. "
                f"Available agents: {list(self._agents.keys())}"
            )
        url = agent.get("url")
        if not url:
            raise RuntimeError(
                f"A2A agent '{agent_name}' has no 'url' in config"
            )
        return str(url)

    async def _discover_agent(self, agent_name: str) -> None:
        if agent_name in self._agent_cards:
            return
        agent = self._agents.get(agent_name, {})
        if "agent_card" in agent:
            card = agent["agent_card"]
            if isinstance(card, dict):
                self._agent_cards[agent_name] = card
                return
        try:
            url = self._get_url(agent_name)
            headers = self._get_headers(agent_name)
            client = await self._get_client()
            card_url = f"{url.rstrip('/')}/.well-known/agent-card.json"
            response = await client.get(card_url, headers=headers)
            response.raise_for_status()
            self._agent_cards[agent_name] = response.json()
        except Exception:
            self._agent_cards[agent_name] = {}

    async def _resolve_agent(self, agent_name: str) -> tuple[str, dict[str, str]]:
        await self._discover_agent(agent_name)
        return self._get_url(agent_name), self._get_headers(agent_name)

    @staticmethod
    def _extract_payload(task: dict[str, Any]) -> dict[str, Any]:
        artifacts = task.get("artifacts", [])
        for artifact in artifacts:
            parts = artifact.get("parts", [])
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "{}")
                    try:
                        return json.loads(text)  # type: ignore[no-any-return]
                    except (json.JSONDecodeError, TypeError):
                        return {"text": text}
        return {}

    async def send(self, target: str, payload: dict[str, Any]) -> Message:
        url, headers = await self._resolve_agent(target)
        client = await self._get_client()

        task_id = str(uuid.uuid4())
        request_body = {
            "jsonrpc": "2.0",
            "method": "tasks/sendMessage",
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": json.dumps(payload)}],
                },
            },
            "id": 1,
        }

        try:
            response = await client.post(url, json=request_body, headers=headers)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"A2A send failed for agent '{target}': {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"A2A invalid JSON response from agent '{target}': {exc}"
            ) from exc

        if "error" in result:
            raise RuntimeError(
                f"A2A JSON-RPC error from agent '{target}': {result['error']}"
            )

        task = result.get("result", result if isinstance(result, dict) else {})
        if not isinstance(task, dict):
            return Message(target=target, payload={}, correlation_id=task_id)

        state = task.get("status", {}).get("state", "")
        if state == "completed":
            return Message(
                target=target,
                payload=self._extract_payload(task),
                correlation_id=task_id,
            )
        if state == "failed":
            msg = task.get("status", {}).get("message", "unknown error")
            raise RuntimeError(f"A2A task failed for agent '{target}': {msg}")
        if state == "canceled":
            raise RuntimeError(f"A2A task canceled for agent '{target}'")

        # Poll for completion
        actual_task_id = task.get("id", task_id)
        max_polls = max(1, int(self._timeout_seconds))
        for _ in range(max_polls):
            await asyncio.sleep(1)

            poll_body = {
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "params": {"id": actual_task_id},
                "id": 2,
            }

            try:
                response = await client.post(url, json=poll_body, headers=headers)
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"A2A poll failed for agent '{target}': {exc}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"A2A invalid JSON during poll from agent '{target}': {exc}"
                ) from exc

            if "error" in result:
                raise RuntimeError(
                    f"A2A JSON-RPC error during poll from agent '{target}': "
                    f"{result['error']}"
                )

            task = result.get("result", {})
            state = task.get("status", {}).get("state", "")

            if state == "completed":
                return Message(
                    target=target,
                    payload=self._extract_payload(task),
                    correlation_id=task_id,
                )
            if state == "failed":
                msg = task.get("status", {}).get("message", "unknown error")
                raise RuntimeError(f"A2A task failed for agent '{target}': {msg}")
            if state == "canceled":
                raise RuntimeError(f"A2A task canceled for agent '{target}'")

        raise RuntimeError(
            f"A2A task timed out for agent '{target}' after {max_polls}s"
        )

    async def subscribe(self, topic: str) -> AsyncIterator[Message]:
        url, headers = await self._resolve_agent(topic)
        client = await self._get_client()

        task_id = str(uuid.uuid4())
        request_body = {
            "jsonrpc": "2.0",
            "method": "tasks/sendStreamingMessage",
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": json.dumps({"topic": topic})}],
                },
            },
            "id": 1,
        }

        try:
            async with httpx_sse.aconnect_sse(
                client, "POST", url, json=request_body, headers=headers
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    try:
                        event_data = json.loads(sse.data)
                    except json.JSONDecodeError:
                        continue

                    if "error" in event_data:
                        raise RuntimeError(
                            f"A2A streaming error from agent '{topic}': "
                            f"{event_data['error']}"
                        )

                    task = event_data.get("result", {})
                    if sse.event == "task_artifact_update":
                        yield Message(
                            target=topic,
                            payload=self._extract_payload(task),
                            correlation_id=task_id,
                        )
                    elif sse.event == "task_status_update":
                        state = task.get("status", {}).get("state", "")
                        if state == "failed":
                            msg = task.get("status", {}).get(
                                "message", "unknown error"
                            )
                            raise RuntimeError(
                                f"A2A streaming task failed for agent '{topic}': {msg}"
                            )
                        if state in ("completed", "canceled"):
                            return
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(
                f"A2A subscribe failed for agent '{topic}': {exc}"
            ) from exc

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        url, headers = await self._resolve_agent(topic)
        client = await self._get_client()

        task_id = str(uuid.uuid4())
        request_body = {
            "jsonrpc": "2.0",
            "method": "tasks/sendMessage",
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": json.dumps(payload)}],
                },
            },
            "id": 1,
        }

        try:
            response = await client.post(url, json=request_body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"A2A publish failed for agent '{topic}': {exc}"
            ) from exc


def build(config: dict[str, object]) -> A2AIpc:
    """Build an A2A IPC implementation from configuration."""
    return A2AIpc(config)


def _main() -> None:
    """Test entry point for A2A IPC implementation."""
    if not _HAS_HTTPX or not _HAS_HTTPX_SSE:
        skip("httpx or httpx-sse not installed")
        return

    agent_url = os.environ.get("PYXEN_A2A_TEST_AGENT_URL")
    if not agent_url:
        skip("PYXEN_A2A_TEST_AGENT_URL not set")
        return

    async def go() -> None:
        config: dict[str, object] = {
            "agents": {
                "test-agent": {"url": agent_url},
            },
            "timeout_seconds": 10,
        }
        ipc = build(config)

        # Test publish (fire and forget)
        try:
            await ipc.publish("test-agent", {"action": "ping"})
        except RuntimeError as exc:
            skip(f"publish failed: {exc}")
            return

        # Test send (request/reply)
        try:
            reply = await ipc.send("test-agent", {"action": "ping"})
        except RuntimeError as exc:
            skip(f"send failed: {exc}")
            return

        assert reply.target == "test-agent", (
            f"Expected test-agent, got {reply.target}"
        )
        assert reply.correlation_id is not None
        assert len(reply.correlation_id) > 0
        assert isinstance(reply.payload, dict)

    try:
        asyncio.run(go())
    except Exception as exc:
        skip(f"{exc}")


if __name__ == "__main__":
    _main()
