"""all_in_one_demo — interactive CLI Agent Playground.

An interactive REPL that exercises all 7 pyxen primitives in a natural
dependency graph rather than a serial walk-through. Each user command
triggers a multi-step workflow that interleaves 4–6 primitives. State
persists across commands via ``rt.storage`` so later commands have real
data dependencies on earlier ones.

Commands:
  deploy      — identity → pkg → tokens → storage → observability → ipc
  diagnostic  — identity → secrets → pkg → storage → tokens → observability → ipc → storage
  report      — identity → secrets → storage → tokens → ipc → observability → storage
  status      — identity → storage → observability
  help        — show available commands
  exit        — leave the playground

Run from the repo root:

    PYTHONPATH=src python examples/all_in_one_demo/main.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyxen import Runtime
from pyxen._paths import project_root

HERE = project_root() / "examples" / "all_in_one_demo"


def _setup_pythonpath() -> None:
    src = project_root() / "src"
    if "PYTHONPATH" not in os.environ and src.is_dir():
        os.environ["PYTHONPATH"] = str(src)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(title: str, body: str = "") -> None:
    try:
        from rich.console import Console
        from rich.text import Text
        c = Console()
        label = Text(title, style="bold cyan")
        if body:
            label.append(f"  {body}", style="dim")
        c.print(label)
    except ImportError:
        print(f"  {title}  {body}".rstrip())


def _d(key: str, value: object) -> None:
    try:
        from rich.console import Console
        c = Console()
        c.print(f"    [green]{key}:[/] {value}")
    except ImportError:
        print(f"    {key}: {value}")


def _w(msg: str) -> None:
    try:
        from rich.console import Console
        c = Console()
        c.print(f"    [yellow]{msg}[/]")
    except ImportError:
        print(f"    {msg}")


def _e(msg: str) -> None:
    try:
        from rich.console import Console
        c = Console()
        c.print(f"    [red]{msg}[/]")
    except ImportError:
        print(f"    {msg}")


def _banner() -> None:
    try:
        from rich.console import Console
        from rich.panel import Panel
        c = Console()
        c.print(Panel.fit(
            "[bold cyan]CLI Agent Playground[/]\n"
            "[dim]Exercise all 7 pyxen primitives in an interactive REPL[/]",
            border_style="cyan",
        ))
    except ImportError:
        print("=" * 50)
        print("  CLI Agent Playground")
        print("  Exercise all 7 pyxen primitives in an interactive REPL")
        print("=" * 50)


def _show_help() -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        c = Console()
        t = Table(title="Commands", box=None, show_header=True)
        t.add_column("Command", style="cyan")
        t.add_column("Description", style="white")
        t.add_row("deploy", "Deploy a service (identity → pkg → tokens → storage → observability → ipc)")
        t.add_row("diagnostic", "Run a diagnostic check (identity → secrets → pkg → storage → tokens → observability → ipc → storage)")
        t.add_row("report", "Generate a summary report (identity → secrets → storage → tokens → ipc → observability → storage)")
        t.add_row("status", "Show current agent state (identity → storage → observability)")
        t.add_row("help", "Show this help")
        t.add_row("exit", "Exit the playground")
        c.print(t)
    except ImportError:
        print("Commands:")
        print("  deploy      Deploy a service")
        print("  diagnostic  Run a diagnostic check")
        print("  report      Generate a summary report")
        print("  status      Show current agent state")
        print("  help        Show this help")
        print("  exit        Exit the playground")


async def cmd_deploy(rt: Runtime) -> None:
    """Deploy a service — uses identity, pkg, tokens, storage, observability, ipc."""
    _p("[cmd] deploy", "Deploying a service...")

    me = await rt.identity.current()
    _d("identity.user", me.id)

    await rt.pkg.ensure_python(["rich"])
    _d("pkg", "packages ensured")

    check = await rt.tokens.check("deploy", 200)
    _d("tokens.check", f"allowed={check.allowed}, remaining={check.remaining}")
    if not check.allowed:
        _w("insufficient budget — deploy aborted")
        return
    await rt.tokens.charge("deploy", tokens=200, dollars=0.0)
    _d("tokens.charge", "200 tokens charged")

    deploy_id = str(uuid.uuid4())
    service = f"svc-{deploy_id[:8]}"
    record = {
        "deploy_id": deploy_id,
        "user": me.id,
        "service": service,
        "status": "deployed",
        "deployed_at": _now_iso(),
    }
    await rt.storage.put("deployments", deploy_id, record)
    _d("storage.put", f"deployment {service} recorded")

    async with rt.observability.trace("deploy") as span:
        span.set_attribute("deploy_id", deploy_id)
        span.set_attribute("service", service)
        span.set_attribute("user", me.id)
        span.log("info", "service deployed", deploy_id=deploy_id)
    _d("observability.trace", "deploy span emitted")

    await rt.ipc.publish("deploy", {
        "event": "deployed",
        "deploy_id": deploy_id,
        "service": service,
        "user": me.id,
    })
    _d("ipc.publish", f"deploy event published for {service}")


async def cmd_diagnostic(rt: Runtime) -> None:
    """Run a diagnostic — uses identity, secrets, pkg, storage, tokens, observability, ipc, storage."""
    _p("[cmd] diagnostic", "Running system diagnostic...")

    me = await rt.identity.current()
    _d("identity.user", me.id)

    api_key = ""
    try:
        api_key = await rt.secrets.get("API_KEY")
        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "(short)"
        _d("secrets.get", f"API_KEY={masked}")
    except Exception:
        _w("API_KEY not loaded (secrets primitive still exercised)")

    await rt.pkg.ensure_python(["rich"])
    _d("pkg", "packages ensured")

    prev = await rt.storage.query("diagnostics")
    _d("storage.query", f"{len(prev)} previous diagnostic(s)")

    check = await rt.tokens.check("diagnostic", 300)
    _d("tokens.check", f"allowed={check.allowed}, remaining={check.remaining}")
    if not check.allowed:
        _w("insufficient budget — diagnostic aborted")
        return
    await rt.tokens.charge("diagnostic", tokens=300, dollars=0.0)
    _d("tokens.charge", "300 tokens charged")

    async with rt.observability.trace("diagnostic") as span:
        span.set_attribute("user", me.id)
        span.set_attribute("previous_runs", str(len(prev)))
        span.log("info", "diagnostic started", api_key_loaded=bool(api_key))
    _d("observability.trace", "diagnostic span emitted")

    diagnostic_id = str(uuid.uuid4())
    await rt.ipc.publish("diagnostic", {
        "event": "diagnostic_run",
        "diagnostic_id": diagnostic_id,
        "user": me.id,
        "previous_runs": len(prev),
    })
    _d("ipc.publish", "diagnostic event published")

    result = {
        "diagnostic_id": diagnostic_id,
        "user": me.id,
        "status": "passed",
        "api_key_loaded": bool(api_key),
        "previous_diagnostics": len(prev),
        "ran_at": _now_iso(),
    }
    await rt.storage.put("diagnostics", diagnostic_id, result)
    _d("storage.put", "diagnostic result saved")


async def cmd_report(rt: Runtime) -> None:
    """Generate a report — uses identity, secrets, storage, tokens, ipc, observability, storage."""
    _p("[cmd] report", "Generating summary report...")

    me = await rt.identity.current()
    _d("identity.user", me.id)

    api_key = ""
    try:
        api_key = await rt.secrets.get("API_KEY")
        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "(short)"
        _d("secrets.get", f"API_KEY={masked}")
    except Exception:
        _w("API_KEY not loaded")

    deployments = await rt.storage.query("deployments")
    diagnostics = await rt.storage.query("diagnostics")
    sessions = await rt.storage.query("sessions")
    _d("storage.query", f"{len(deployments)} deployment(s), {len(diagnostics)} diagnostic(s)")

    check = await rt.tokens.check("report", 400)
    _d("tokens.check", f"allowed={check.allowed}, remaining={check.remaining}")
    if not check.allowed:
        _w("insufficient budget — report aborted")
        return
    await rt.tokens.charge("report", tokens=400, dollars=0.0)
    _d("tokens.charge", "400 tokens charged")

    report_id = str(uuid.uuid4())
    await rt.ipc.publish("report", {
        "event": "report_generated",
        "report_id": report_id,
        "user": me.id,
        "deployments": len(deployments),
        "diagnostics": len(diagnostics),
    })
    _d("ipc.publish", "report event published")

    async with rt.observability.trace("report") as span:
        span.set_attribute("report_id", report_id)
        span.set_attribute("user", me.id)
        span.set_attribute("num_deployments", str(len(deployments)))
        span.set_attribute("num_diagnostics", str(len(diagnostics)))
        span.log("info", "report generated",
                 deployments=len(deployments),
                 diagnostics=len(diagnostics))
    _d("observability.trace", "report span emitted")

    content_lines = [
        f"Summary Report ({_now_iso()})",
        f"User: {me.id}",
        f"Deployments: {len(deployments)}",
        f"Diagnostics: {len(diagnostics)}",
        f"Sessions: {len(sessions)}",
    ]
    if deployments:
        content_lines.append("--- Deployments ---")
        for d in deployments:
            content_lines.append(f"  {d.get('service', '?')}: {d.get('status', '?')}")
    if diagnostics:
        content_lines.append("--- Diagnostics ---")
        for d in diagnostics:
            content_lines.append(f"  {d.get('diagnostic_id', '?')[:12]}...: {d.get('status', '?')}")
    content = "\n".join(content_lines)

    report = {
        "report_id": report_id,
        "user": me.id,
        "content": content,
        "num_deployments": len(deployments),
        "num_diagnostics": len(diagnostics),
        "generated_at": _now_iso(),
    }
    await rt.storage.put("reports", report_id, report)
    _d("storage.put", "report saved")


async def cmd_status(rt: Runtime) -> None:
    """Show agent state — uses identity, storage, observability."""
    _p("[cmd] status", "Querying current agent state...")

    me = await rt.identity.current()
    _d("identity.user", me.id)

    deployments = await rt.storage.query("deployments")
    diagnostics = await rt.storage.query("diagnostics")
    reports = await rt.storage.query("reports")
    sessions = await rt.storage.query("sessions")

    _d("storage.sessions", len(sessions))
    _d("storage.deployments", len(deployments))
    _d("storage.diagnostics", len(diagnostics))
    _d("storage.reports", len(reports))

    async with rt.observability.trace("status") as span:
        span.set_attribute("user", me.id)
        span.set_attribute("num_sessions", str(len(sessions)))
        span.set_attribute("num_deployments", str(len(deployments)))
        span.set_attribute("num_diagnostics", str(len(diagnostics)))
        span.set_attribute("num_reports", str(len(reports)))
        span.log("info", "status checked")

    _summary_table([
        ("sessions", str(len(sessions))),
        ("deployments", str(len(deployments))),
        ("diagnostics", str(len(diagnostics))),
        ("reports", str(len(reports))),
    ])


def _summary_table(rows: list[tuple[str, str]]) -> None:
    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table
        c = Console()
        t = Table(title="Agent State", box=box.ROUNDED)
        t.add_column("Namespace", style="cyan")
        t.add_column("Count", style="green")
        for name, count in rows:
            t.add_row(name, count)
        c.print()
        c.print(t)
    except ImportError:
        print()
        print("─" * 40)
        print("  Agent State")
        print("─" * 40)
        for name, count in rows:
            print(f"  {name:20s} {count}")
        print("─" * 40)


CMDS: dict[str, object] = {
    "deploy": cmd_deploy,
    "diagnostic": cmd_diagnostic,
    "report": cmd_report,
    "status": cmd_status,
}


async def _repl(rt: Runtime) -> None:
    """Read commands from stdin and dispatch them until exit."""
    _banner()
    me = await rt.identity.current()
    _p("session.start", f"Welcome, {me.id}! Type 'help' for commands.")

    session_id = str(uuid.uuid4())
    await rt.storage.put("sessions", session_id, {
        "session_id": session_id,
        "user": me.id,
        "started_at": _now_iso(),
    })

    while True:
        try:
            raw = await asyncio.to_thread(input, "pyxen> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        cmd = raw.strip().lower()

        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            _show_help()
        elif cmd == "":
            continue
        elif cmd in CMDS:
            try:
                await CMDS[cmd](rt)  # type: ignore[operator]
            except Exception as exc:
                _e(f"command failed: {exc}")
        else:
            _w(f"unknown command: {cmd!r} (try 'help')")

    _p("session.end", "Goodbye!")


async def _async_main() -> None:
    rt = await Runtime.load(HERE / "runtime.json")
    await _repl(rt)


def main() -> None:
    _setup_pythonpath()
    asyncio.run(_async_main())


# ── Self-test ────────────────────────────────────────────────────────────────

def _main() -> None:
    """Self-test entry point for pyxen-test discovery.

    Creates a hermetic runtime with in-memory backends and pipes commands
    through the REPL loop headlessly, verifying storage and IPC outcomes.
    """
    import io
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)

        env_path = Path(tmp) / ".env"
        env_path.write_text("API_KEY=sk-test-fake-key-for-self-test\n")

        budget_path = Path(tmp) / "budget.json"
        budget_path.write_text('{"daily_limit": 100000}\n')

        manifest = {
            "version": "1",
            "identity": {"implementation": "env", "config": {}},
            "tokens": {"implementation": "json_budget", "config": {"path": str(budget_path), "daily_limit": 100000}},
            "ipc": {"implementation": "inproc", "config": {}},
            "pkg": {"implementation": "dry_run", "config": {}},
            "storage": {"implementation": "inmemory", "config": {}},
            "secrets": {"implementation": "dotenv", "config": {"path": str(env_path)}},
            "observability": {"implementation": "null", "config": {}},
        }

        rt_path = Path(tmp) / "runtime.json"
        rt_path.write_text(json.dumps(manifest))
        os.environ["PYXEN_IDENTITY_ID"] = "test-bot"

        async def go() -> None:
            rt = await Runtime.load(str(rt_path))

            deploy_msgs: list[dict[str, Any]] = []
            diag_msgs: list[dict[str, Any]] = []
            report_msgs: list[dict[str, Any]] = []

            async def _collect(topic: str, dest: list[dict[str, Any]]) -> None:
                async for msg in rt.ipc.subscribe(topic):
                    dest.append(msg.payload)

            collectors = [
                asyncio.create_task(_collect("deploy", deploy_msgs)),
                asyncio.create_task(_collect("diagnostic", diag_msgs)),
                asyncio.create_task(_collect("report", report_msgs)),
            ]
            await asyncio.sleep(0.05)

            old_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO("deploy\ndiagnostic\nreport\nstatus\nexit\n")
                await _repl(rt)
            finally:
                sys.stdin = old_stdin

            await asyncio.sleep(0.1)
            for t in collectors:
                t.cancel()
            await asyncio.gather(*collectors, return_exceptions=True)

            deploys = await rt.storage.query("deployments")
            diags = await rt.storage.query("diagnostics")
            reports = await rt.storage.query("reports")

            assert len(deploys) == 1, f"expected 1 deployment, got {len(deploys)}"
            assert deploys[0]["user"] == "test-bot"
            assert deploys[0]["status"] == "deployed"

            assert len(diags) == 1, f"expected 1 diagnostic, got {len(diags)}"
            assert diags[0]["user"] == "test-bot"
            assert diags[0]["status"] == "passed"

            assert len(reports) == 1, f"expected 1 report, got {len(reports)}"
            assert reports[0]["num_deployments"] == 1
            assert reports[0]["num_diagnostics"] == 1

            assert len(deploy_msgs) == 1
            assert deploy_msgs[0]["event"] == "deployed"

            assert len(diag_msgs) == 1
            assert diag_msgs[0]["event"] == "diagnostic_run"

            assert len(report_msgs) == 1
            assert report_msgs[0]["event"] == "report_generated"

            print()
            print("all_in_one_demo _main() — ALL TESTS PASSED")

        _setup_pythonpath()
        asyncio.run(go())


if __name__ == "__main__":
    _setup_pythonpath()
    asyncio.run(_async_main())
