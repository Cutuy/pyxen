"""The ``Runtime`` class — the entry point that loads a manifest and exposes
the 7 primitive attributes.

The runtime is intentionally thin. It reads ``runtime.json``, looks up the
implementation registry for each declared primitive, instantiates the impl
with its config, and exposes the result as an attribute. The application
code never imports an implementation directly; it only ever sees
``rt.identity``, ``rt.tokens``, ``rt.ipc``, etc.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .errors import ImplementationNotFoundError
from .manifest import Manifest, load_manifest

# Map a primitive name to:
#   (the core interface, the default impl module path under ``pyxen.impl``)
# Adding a new primitive means: add an interface in core, add a binding
# here, add an impl sub-package, and update the manifest schema.
PRIMITIVE_TABLE: dict[str, str] = {
    "identity": "pyxen.impl.identity",
    "tokens": "pyxen.impl.tokens",
    "ipc": "pyxen.impl.ipc",
    "pkg": "pyxen.impl.pkg",
    "storage": "pyxen.impl.storage",
    "secrets": "pyxen.impl.secrets",
    "observability": "pyxen.impl.observability",
}


class Runtime:
    """The runtime instance, bound to a particular manifest.

    A ``Runtime`` is loaded once at app startup:

        rt = await Runtime.load("runtime.json")

    The resulting object's attributes (``rt.identity``, ``rt.tokens``,
    etc.) are the configured implementations. The application code never
    imports an implementation directly.
    """

    manifest: Manifest

    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self._impls: dict[str, Any] = {}

    @classmethod
    async def load(cls, path: str | Path) -> Runtime:
        """Load a runtime from a ``runtime.json`` file.

        Resolves and instantiates every declared primitive binding. Primitives
        that aren't declared in the manifest are left as ``None`` — the app
        can either handle the absence (try/except AttributeError) or assert
        they're present at startup.
        """
        manifest = load_manifest(path)
        rt = cls(manifest)
        for primitive, binding in manifest.bindings.items():
            impl = await cls._instantiate(primitive, binding.implementation, binding.config)
            rt._impls[primitive] = impl
        return rt

    @staticmethod
    async def _instantiate(
        primitive: str, implementation: str, config: dict[str, Any]
    ) -> Any:
        """Resolve an implementation module and call its ``build(config)``."""
        package = PRIMITIVE_TABLE.get(primitive)
        if package is None:
            raise ImplementationNotFoundError(
                f"unknown primitive '{primitive}'"
            )
        module_name = f"{package}.{implementation}"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ImplementationNotFoundError(
                f"implementation module '{module_name}' not found "
                f"(for primitive '{primitive}'): {exc}"
            ) from exc
        build = getattr(module, "build", None)
        if build is None:
            raise ImplementationNotFoundError(
                f"implementation module '{module_name}' is missing a 'build' function"
            )
        result = build(config)
        if hasattr(result, "__await__"):
            result = await result
        return result

    def __getattr__(self, name: str) -> Any:
        # Only consulted for attributes not found via normal lookup.
        if name.startswith("_"):
            raise AttributeError(name)
        impl = self._impls.get(name)
        if impl is None:
            raise AttributeError(
                f"runtime has no '{name}' primitive; "
                f"declare it in runtime.json or check the name"
            )
        return impl


def _main() -> None:
    """Test entry point for this module. Covers the Runtime entry point thoroughly."""
    import asyncio
    import json
    import tempfile
    from pathlib import Path

    from .errors import ImplementationNotFoundError, ManifestError

    async def run_tests() -> None:
        # --- Full manifest: all 7 primitives, in-memory local impls ---
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "version": "1",
                "identity": {"implementation": "env", "config": {}},
                "tokens": {"implementation": "json_budget", "config": {"path": str(Path(tmp) / "b.json")}},
                "ipc": {"implementation": "inproc", "config": {}},
                "pkg": {"implementation": "dry_run", "config": {}},
                "storage": {"implementation": "inmemory", "config": {}},
                "secrets": {"implementation": "dotenv", "config": {"path": str(Path(tmp) / ".env")}},
                "observability": {"implementation": "null", "config": {}},
            }
            f = Path(tmp) / "runtime.json"
            f.write_text(json.dumps(manifest))

            rt = await Runtime.load(f)

            # All 7 primitives resolved
            assert rt.identity is not None
            assert rt.tokens is not None
            assert rt.ipc is not None
            assert rt.pkg is not None
            assert rt.storage is not None
            assert rt.secrets is not None
            assert rt.observability is not None

            # Identity works
            me = await rt.identity.current()
            assert me.id == "anonymous"  # PYXEN_IDENTITY_ID unset in test env
            assert me.source == "env"

            # Storage works (put then get)
            await rt.storage.put("ns", "k", {"v": 1, "x": "y"})
            got = await rt.storage.get("ns", "k")
            assert got == {"v": 1, "x": "y"}

            # Storage get on missing key returns None
            assert await rt.storage.get("ns", "missing") is None

            # Storage namespace isolation
            await rt.storage.put("other", "k", {"v": 2})
            assert await rt.storage.get("ns", "k") == {"v": 1, "x": "y"}
            assert await rt.storage.get("other", "k") == {"v": 2}

            # Tokens check
            check = await rt.tokens.check("gpt-4o", 1000)
            assert check.allowed is True
            assert check.remaining >= 0

            # Observability span context manager
            async with rt.observability.trace("test") as span:
                span.set_attribute("k", "v")
                span.log("info", "msg", extra=42)

            # Manifest is exposed
            assert rt.manifest.version == "1"
            assert len(rt.manifest.bindings) == 7

        # --- Partial manifest: only some primitives declared ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(
                json.dumps({"version": "1", "storage": {"implementation": "inmemory", "config": {}}})
            )
            rt_partial = await Runtime.load(f)
            assert rt_partial.storage is not None
            # Undeclared primitives raise AttributeError on access
            try:
                _ = rt_partial.identity
            except AttributeError as e:
                assert "identity" in str(e)
            else:
                raise AssertionError("undeclared primitive should raise AttributeError")

        # --- Unknown primitive in manifest is silently ignored ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "totally_made_up": {"implementation": "x", "config": {}},
                    }
                )
            )
            # Should NOT raise — unknown primitives are tolerated
            rt_unknown = await Runtime.load(f)
            assert rt_unknown is not None

        # --- Unknown implementation module raises ImplementationNotFoundError ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "storage": {"implementation": "definitely_not_a_real_impl", "config": {}},
                    }
                )
            )
            try:
                await Runtime.load(f)
            except ImplementationNotFoundError as e:
                assert "definitely_not_a_real_impl" in str(e)
            else:
                raise AssertionError("should have raised ImplementationNotFoundError")

        # --- Malformed manifest raises ManifestError ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text("{ bad json")
            try:
                await Runtime.load(f)
            except ManifestError:
                pass
            else:
                raise AssertionError("malformed JSON should raise ManifestError")

        # --- Manifest with pkg dry_run and custom config ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(json.dumps({
                "version": "1",
                "pkg": {"implementation": "dry_run", "config": {"extra": "data"}},
            }))
            rt_pkg = await Runtime.load(f)
            assert rt_pkg.pkg is not None
            await rt_pkg.pkg.ensure_python(["requests>=2.0"])
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
                tf.write(b"requests\n")
                tf_path = tf.name
            try:
                await rt_pkg.pkg.ensure_from_manifest(tf_path)
            finally:
                Path(tf_path).unlink()
            # ensure_from_manifest on missing file is a no-op
            await rt_pkg.pkg.ensure_from_manifest("/nonexistent/pyproject.toml")

        # --- Manifest with pkg pip (requires pip on PATH) ---
        import shutil as _shutil2
        if _shutil2.which("pip"):
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({
                    "version": "1",
                    "pkg": {"implementation": "pip", "config": {}},
                }))
                rt_pip = await Runtime.load(f)
                assert rt_pip.pkg is not None
                snap = await rt_pip.pkg.snapshot()
                assert isinstance(snap.packages, list)
                assert snap.timestamp > 0
                names = {p.name.lower() for p in snap.packages}
                assert "pyxen" in names

        # --- Runtime __getattr__ for non-existent raises AttributeError ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(json.dumps({"version": "1"}))
            rt_min = await Runtime.load(f)
            try:
                _ = rt_min.nonexistent_primitive
            except AttributeError as e:
                assert "nonexistent_primitive" in str(e)
            else:
                raise AssertionError("should raise AttributeError for non-existent primitive")

        # --- Private attribute access raises AttributeError ---
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "runtime.json"
            f.write_text(json.dumps({"version": "1"}))
            rt_min = await Runtime.load(f)
            import contextlib
            with contextlib.suppress(AttributeError):
                _ = rt_min.__dict__  # private, raises

    asyncio.run(run_tests())


if __name__ == "__main__":
    _main()
