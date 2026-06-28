"""``mcp`` ipc impl — Model Context Protocol client communication.

Connects to external MCP servers (stdio or SSE transport) and maps
``send(target, payload)`` to ``call_tool`` on the configured server.
``subscribe`` and ``publish`` are minimal stubs.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ...core.ipc import Message

try:
    from mcp.client.session import ClientSession as _McpClientSession
    from mcp.client.stdio import stdio_client as _mcp_stdio_client
    from mcp.client.stdio import StdioServerParameters as _StdioServerParameters
    from mcp.client.sse import sse_client as _mcp_sse_client
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False


class McpIpc:
    """Model Context Protocol (MCP) client IPC implementation.

    Connects to external MCP servers over stdio or SSE transport and maps
    ``send(target, payload)`` to ``call_tool`` on the configured server.

    Config shape::

        {
            'agents': {
                'agent-name': {
                    'transport': 'stdio',             # 'stdio' or 'sse'
                    'command': ['python', '-m', 'mcp_server'],  # stdio
                    'url': 'http://host:8000/mcp',             # sse
                }
            },
            'timeout_seconds': 30,
        }
    """

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_MCP:
            raise RuntimeError(
                "mcp SDK is required for MCP IPC. "
                "Install with: pip install pyxen[mcp]"
            )
        self._config = config
        timeout_val = config.get("timeout_seconds", 30)
        self._timeout_seconds = float(timeout_val) if isinstance(timeout_val, (int, float)) else 30.0
        agents_raw = config.get("agents", {})
        if not isinstance(agents_raw, dict):
            raise RuntimeError(
                "MCP config: 'agents' must be a dict mapping names to agent configs"
            )
        self._agents: dict[str, dict[str, object]] = agents_raw

    async def _call_tool(
        self, agent_name: str, tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        agent = self._agents.get(agent_name)
        if agent is None:
            raise RuntimeError(
                f"MCP agent '{agent_name}' not found in config. "
                f"Available agents: {list(self._agents.keys())}"
            )
        transport_type = str(agent.get("transport", "stdio"))

        if transport_type == "stdio":
            raw_cmd = agent.get("command")
            if not raw_cmd or not isinstance(raw_cmd, list):
                raise RuntimeError(
                    f"MCP agent '{agent_name}': 'command' must be a list "
                    f"of strings for stdio transport"
                )
            cmd_list: list[str] = [str(c) for c in raw_cmd]
            params = _StdioServerParameters(command=cmd_list[0], args=cmd_list[1:])
            transport_cm = _mcp_stdio_client(params)
        elif transport_type == "sse":
            raw_url = agent.get("url")
            if not raw_url:
                raise RuntimeError(
                    f"MCP agent '{agent_name}': 'url' is required for sse "
                    f"transport"
                )
            transport_cm = _mcp_sse_client(str(raw_url))
        else:
            raise RuntimeError(
                f"MCP agent '{agent_name}': unknown transport "
                f"'{transport_type}' (expected 'stdio' or 'sse')"
            )

        async with transport_cm as (read, write):
            try:
                async with _McpClientSession(read, write) as session:
                    await session.initialize()
                    result = await asyncio.wait_for(
                        session.call_tool(tool, arguments),
                        timeout=self._timeout_seconds,
                    )
                    payload: dict[str, Any] = {}
                    if hasattr(result, "content"):
                        texts: list[str] = []
                        for item in result.content:
                            if hasattr(item, "text"):
                                texts.append(item.text)
                        if len(texts) == 1:
                            try:
                                payload = json.loads(texts[0])
                            except (json.JSONDecodeError, TypeError):
                                payload = {"text": texts[0]}
                        elif texts:
                            payload = {"texts": texts}
                    payload["_is_error"] = getattr(result, "isError", False)
                    return payload
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"MCP call_tool timed out for agent '{agent_name}' "
                    f"after {self._timeout_seconds}s"
                )
            except Exception as exc:
                raise RuntimeError(
                    f"MCP call_tool failed for agent '{agent_name}': {exc}"
                ) from exc

    async def send(self, target: str, payload: dict[str, Any]) -> Message:
        correlation_id = str(uuid.uuid4())
        tool = str(payload.get("tool", "send"))
        arguments = {k: v for k, v in payload.items() if k != "tool"}
        try:
            result_payload = await self._call_tool(target, tool, arguments)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"MCP send failed for agent '{target}': {exc}"
            ) from exc
        return Message(
            target=target,
            payload=result_payload,
            correlation_id=correlation_id,
        )

    async def subscribe(self, topic: str) -> AsyncIterator[Message]:
        raise NotImplementedError("MCP subscribe is not yet implemented")

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        pass


def build(config: dict[str, object]) -> McpIpc:
    """Build an MCP IPC implementation from configuration."""
    return McpIpc(config)


def _main() -> None:
    """Test entry point for MCP IPC implementation."""
    from pyxen._testlib import skip

    if not _HAS_MCP:
        skip("mcp SDK not installed")
        return

    transport = os.environ.get("PYXEN_MCP_TEST_TRANSPORT", "stdio")
    agent_url = os.environ.get("PYXEN_MCP_TEST_AGENT_URL")
    agent_command_str = os.environ.get("PYXEN_MCP_TEST_AGENT_COMMAND")
    agent_command = agent_command_str.split() if agent_command_str else None

    if transport == "sse" and not agent_url:
        skip("PYXEN_MCP_TEST_AGENT_URL not set")
        return
    if transport == "stdio" and not agent_command:
        skip("PYXEN_MCP_TEST_AGENT_COMMAND not set")
        return

    async def _run_tests() -> None:
        from pyxen._testlib import arun_tests

        agent_config: dict[str, object] = (
            {"transport": "stdio", "command": agent_command}
            if transport == "stdio"
            else {"transport": "sse", "url": agent_url}
        )
        config: dict[str, object] = {
            "agents": {"test-agent": agent_config},
            "timeout_seconds": 10,
        }
        ipc = build(config)

        async def test_send() -> None:
            try:
                reply = await ipc.send("test-agent", {"tool": "ping", "message": "hello"})
            except (RuntimeError, NotImplementedError) as exc:
                skip(f"send failed: {exc}")
                return
            assert reply.target == "test-agent"
            assert reply.correlation_id is not None
            assert len(reply.correlation_id) > 0
            assert isinstance(reply.payload, dict)

        await arun_tests(test_send)

    try:
        asyncio.run(_run_tests())
    except Exception as exc:
        skip(f"{exc}")


if __name__ == "__main__":
    _main()
