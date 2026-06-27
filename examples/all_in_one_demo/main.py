"""all_in_one_demo — exercise all 7 pyxen primitives + cron extension.

A "Dev Session Tracker" CLI app that walks through every primitive
in a single coherent workflow: identity → secrets → pkg → storage
→ tokens → observability → ipc → cron.

Fun output uses ``rich`` if installed; falls back to plain print otherwise.

Run from the repo root:

    PYTHONPATH=src python examples/all_in_one_demo/main.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

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


def _summary(rows: list[tuple[str, str]]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        c = Console()
        t = Table(title="Dev Session Summary", box=box.ROUNDED)
        t.add_column("Primitive", style="cyan")
        t.add_column("Status", style="green")
        for name, status in rows:
            t.add_row(name, status)
        c.print()
        c.print(t)
    except ImportError:
        print()
        print("─" * 50)
        print("  Dev Session Summary")
        print("─" * 50)
        for name, status in rows:
            print(f"  {name:20s} {status}")
        print("─" * 50)


async def _ipc_listener(rt: Runtime) -> None:
    try:
        async for msg in rt.ipc.subscribe("session"):
            _d("[ipc] received", msg.payload)
    except asyncio.CancelledError:
        pass


async def main() -> None:
    rt = await Runtime.load(HERE / "runtime.json")
    _primitives: list[str] = []

    # ── 1. Identity ──────────────────────────────────────────────────
    _primitives.append("identity")
    _p("[1/8] Identity", "env — who's running this?")
    me = await rt.identity.current()
    _d("user id", me.id)
    _d("source", me.source)

    # ── 2. Secrets ───────────────────────────────────────────────────
    _primitives.append("secrets")
    _p("[2/8] Secrets", "dotenv — load API key from .env")
    try:
        api_key = await rt.secrets.get("API_KEY")
        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "(short)"
        _d("API_KEY", masked)
    except Exception as e:
        api_key = ""
        _w(f"API_KEY not found: {e}")
        _w("  create .env with API_KEY=sk-... to exercise secrets")

    # ── 3. Pkg ───────────────────────────────────────────────────────
    _primitives.append("pkg")
    _p("[3/8] Pkg", "dry_run — verify/snapshot dependencies")
    await rt.pkg.ensure_python(["rich"])
    _d("ensure_python", "rich (dry run)")
    await rt.pkg.ensure_from_manifest("requirements.txt")
    _d("ensure_from_manifest", "requirements.txt (dry run)")

    # ── 4. Storage ───────────────────────────────────────────────────
    _primitives.append("storage")
    _p("[4/8] Storage", "local_sqlite — persist session record")
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "user": me.id,
        "started_at": _now_iso(),
        "primitives": _primitives[:],
    }
    await rt.storage.put("sessions", session_id, session)
    stored = await rt.storage.get("sessions", session_id)
    ok = stored is not None and stored.get("session_id") == session_id
    _d("session stored", f"{session_id[:12]}...  round-trip={'OK' if ok else 'FAIL'}")

    # ── 5. Tokens ────────────────────────────────────────────────────
    _primitives.append("tokens")
    _p("[5/8] Tokens", "json_budget — check budget & charge")
    check = await rt.tokens.check("demo-run", 500)
    _d("budget check", f"allowed={check.allowed}, remaining={check.remaining}")
    if check.allowed:
        await rt.tokens.charge("demo-run", tokens=500, dollars=0.0)
        _d("charged", "500 tokens (demo-run)")

    # ── 6. Observability ─────────────────────────────────────────────
    _primitives.append("observability")
    _p("[6/8] Observability", "stdout — trace the session")
    async with rt.observability.trace("all-in-one-demo") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("user", me.id)
        span.set_attribute("primitives", ",".join(_primitives))
        span.log("info", "all seven primitives exercised")
    _d("trace emitted", "all-in-one-demo (see JSON lines above)")

    # ── 7. IPC ───────────────────────────────────────────────────────
    _primitives.append("ipc")
    _p("[7/8] IPC", "inproc — publish/subscribe events")
    listener = asyncio.create_task(_ipc_listener(rt))
    await asyncio.sleep(0.05)
    await rt.ipc.publish("session", {"event": "session_start", "session_id": session_id, "user": me.id})
    await rt.ipc.publish("session", {"event": "primitives_done", "session_id": session_id, "primitives": _primitives[:]})
    await asyncio.sleep(0.05)
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        pass

    # ── 8. Cron ──────────────────────────────────────────────────────
    _p("[8/8] Cron", "extension — list scheduled jobs")
    cron_jobs = 0
    if hasattr(rt, "cron"):
        jobs = await rt.cron.list()
        cron_jobs = len(jobs)
        _d("jobs declared", cron_jobs)
        for job in jobs:
            s = await rt.cron.status(job.name)
            status = "active" if s and s.enabled else "disabled"
            _d(f"  [{status}] {job.name}", job.schedule)
    else:
        _w("(no cron backend available)")

    # ── Summary ──────────────────────────────────────────────────────
    _summary([
        ("Identity", me.id),
        ("Secrets", "loaded" if api_key else "skipped (no .env)"),
        ("Pkg", "dry-run OK"),
        ("Storage", "session stored"),
        ("Tokens", f"allowed={check.allowed}"),
        ("Observability", "trace emitted"),
        ("IPC", "2 events published"),
        ("Cron", f"{cron_jobs} job(s)"),
    ])


def _main() -> None:
    """Self-test entry point for pyxen-test discovery.

    Creates hermetic temp files so the test doesn't depend on the
    user's .env or external state.
    """
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

            # 1. Identity
            me = await rt.identity.current()
            assert me.id == "test-bot"

            # 2. Secrets
            key = await rt.secrets.get("API_KEY")
            assert key == "sk-test-fake-key-for-self-test"

            # 3. Pkg
            await rt.pkg.ensure_python(["rich>=13.0"])
            await rt.pkg.ensure_from_manifest("requirements.txt")

            # 4. Storage
            await rt.storage.put("sessions", me.id, {"user": me.id, "status": "started"})
            record = await rt.storage.get("sessions", me.id)
            assert record is not None
            assert record["status"] == "started"

            # 5. Tokens
            check = await rt.tokens.check("gpt-4o", 500)
            assert check.allowed is True
            await rt.tokens.charge("gpt-4o", tokens=500, dollars=0.0)

            # 6. Observability
            async with rt.observability.trace("dev-session") as span:
                span.set_attribute("user", me.id)
                span.log("info", "test session")

            # 7. IPC
            received: list[dict] = []

            async def listener() -> None:
                async for msg in rt.ipc.subscribe("events"):
                    received.append(msg.payload)
                    return

            task = asyncio.create_task(listener())
            await asyncio.sleep(0.05)
            await rt.ipc.publish("events", {"event": "ping"})
            await asyncio.wait_for(task, timeout=2.0)
            assert len(received) == 1
            assert received[0]["event"] == "ping"

            # Verify no cron in this test manifest
            assert "cron" not in rt.manifest.extensions

            print("all_in_one_demo _main() — ALL TESTS PASSED")

        _setup_pythonpath()
        asyncio.run(go())


if __name__ == "__main__":
    _setup_pythonpath()
    asyncio.run(main())
