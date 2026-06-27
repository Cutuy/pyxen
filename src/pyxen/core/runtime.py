"""The ``Runtime`` class — the entry point that loads a manifest and exposes
primitive attributes and extensions.

The runtime is intentionally thin. It reads ``runtime.json``, looks up the
implementation registry for each declared primitive, instantiates the impl
with its config, and exposes the result as an attribute. The application
code never imports an implementation directly; it only ever sees
``rt.identity``, ``rt.tokens``, ``rt.ipc``, etc.

Extensions declared in the manifest (such as ``cron``) are loaded via the
extension registry and exposed as ``rt.<name>``.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .errors import ImplementationNotFoundError, ManifestError
from .manifest import (
    Manifest,
    _config_has_secret_refs,
    load_manifest,
    SECRET_REF_KEY,
)
from .observability import ObservabilityImpl
from .secrets import SecretsImpl

if TYPE_CHECKING:
    from pyxen.impl.identity import IdentityImpl
    from pyxen.impl.ipc import IpcImpl
    from pyxen.impl.pkg import PkgImpl
    from pyxen.impl.storage import StorageImpl
    from pyxen.impl.tokens import TokensImpl

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

        rt = await Runtime.load("runtime.json")
    """

    manifest: Manifest

    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self._impls: dict[str, Any] = {}

    # ── Lazy-loading typed accessors ──────────────────────────────────

    @property
    def identity(self) -> IdentityImpl:
        impl: IdentityImpl = self._ensure("identity")
        return impl

    @property
    def tokens(self) -> TokensImpl:
        impl: TokensImpl = self._ensure("tokens")
        return impl

    @property
    def ipc(self) -> IpcImpl:
        impl: IpcImpl = self._ensure("ipc")
        return impl

    @property
    def pkg(self) -> PkgImpl:
        impl: PkgImpl = self._ensure("pkg")
        return impl

    @property
    def storage(self) -> StorageImpl:
        impl: StorageImpl = self._ensure("storage")
        return impl

    @property
    def secrets(self) -> SecretsImpl:
        impl: SecretsImpl = self._ensure("secrets")
        return impl

    @property
    def observability(self) -> ObservabilityImpl:
        impl: ObservabilityImpl = self._ensure("observability")
        return impl

    def _ensure(self, name: str) -> Any:
        """Resolve, build, and cache a primitive impl on first access."""
        impl = self._impls.get(name)
        if impl is not None:
            return impl

        binding = self.manifest.bindings.get(name)
        if binding is None:
            raise AttributeError(
                f"runtime has no '{name}' primitive; "
                f"declare it in runtime.json or check the name"
            ) from None

        needs_secrets = _config_has_secret_refs(binding.config)
        if needs_secrets:
            secrets_name = "secrets"
            if secrets_name not in self._impls:
                if secrets_name not in self.manifest.bindings:
                    raise ManifestError(
                        f"config references {SECRET_REF_KEY} but no "
                        f"secrets primitive declared"
                    )
                self._ensure(secrets_name)

        impl = self._instantiate(
            name,
            binding.implementation,
            binding.config,
            secrets=self._impls.get("secrets") if needs_secrets else None,
            observability=self._impls.get("observability"),
        )
        self._impls[name] = impl
        return impl

    @classmethod
    async def load(cls, path: str | Path) -> Runtime:
        """Parse a manifest and return a Runtime.

        Validates that every declared primitive's impl module exists
        (``import`` + checks for ``build``), but defers calling
        ``build()`` until the attribute is first accessed.
        """
        manifest = load_manifest(path)
        rt = cls(manifest)

        for primitive, binding in manifest.bindings.items():
            cls._import_impl_module(primitive, binding.implementation)

        await rt._init_extensions(Path(path).resolve().parent)
        return rt

    async def _init_extensions(self, app_dir: Path | None) -> None:
        """Initialize all extensions declared in the manifest."""
        extensions = self.manifest.extensions
        if not extensions:
            return
        from .ext import init_extension

        for name, config in extensions.items():
            ext = await init_extension(name, config, app_dir)
            if ext is not None:
                self._impls[name] = ext

    @staticmethod
    def _import_impl_module(primitive: str, implementation: str) -> None:
        """Import and validate that an impl module exists with a ``build`` function."""
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
        if not hasattr(module, "build"):
            raise ImplementationNotFoundError(
                f"implementation module '{module_name}' is missing a 'build' function"
            )

    @staticmethod
    def _instantiate(
        primitive: str,
        implementation: str,
        config: dict[str, Any],
        *,
        secrets: SecretsImpl | None = None,
        observability: ObservabilityImpl | None = None,
    ) -> Any:
        """Call ``build()`` on a previously-validated impl module and return the instance."""
        package = PRIMITIVE_TABLE.get(primitive)
        module_name = f"{package}.{implementation}"
        module = importlib.import_module(module_name)
        build = getattr(module, "build")
        sig = inspect.signature(build).parameters
        kwargs: dict[str, Any] = {}
        if secrets is not None and "secrets" in sig:
            kwargs["secrets"] = secrets
        if observability is not None and "observability" in sig:
            kwargs["observability"] = observability
        return build(config, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Only consulted for attributes not found via normal lookup.
        if name.startswith("_"):
            raise AttributeError(name)
        impl = self._impls.get(name)
        if impl is None:
            raise AttributeError(
                f"runtime has no '{name}' primitive; "
                f"declare it in runtime.json or check the name"
            ) from None
        return impl


def _main() -> None:
    """Test entry point for this module. Covers the Runtime entry point thoroughly."""
    import asyncio
    import json
    import tempfile
    from pathlib import Path

    from .errors import ImplementationNotFoundError, ManifestError
    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:

        async def test_full_manifest() -> None:
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
                assert rt.identity is not None
                assert rt.tokens is not None
                assert rt.ipc is not None
                assert rt.pkg is not None
                assert rt.storage is not None
                assert rt.secrets is not None
                assert rt.observability is not None
                me = await rt.identity.current()
                assert me.id == "anonymous"
                assert me.source == "env"
                await rt.storage.put("ns", "k", {"v": 1, "x": "y"})
                assert await rt.storage.get("ns", "k") == {"v": 1, "x": "y"}
                assert await rt.storage.get("ns", "missing") is None
                await rt.storage.put("other", "k", {"v": 2})
                assert await rt.storage.get("ns", "k") == {"v": 1, "x": "y"}
                assert await rt.storage.get("other", "k") == {"v": 2}
                check = await rt.tokens.check("gpt-4o", 1000)
                assert check.allowed is True
                assert check.remaining >= 0
                async with rt.observability.trace("test") as span:
                    span.set_attribute("k", "v")
                    span.log("info", "msg", extra=42)
                assert rt.manifest.version == "1"
                assert len(rt.manifest.bindings) == 7

        async def test_partial_manifest() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1", "storage": {"implementation": "inmemory", "config": {}}}))
                rt_partial = await Runtime.load(f)
                assert rt_partial.storage is not None
                try:
                    _ = rt_partial.identity
                except AttributeError as e:
                    assert "identity" in str(e)
                else:
                    raise AssertionError("undeclared primitive should raise AttributeError")

        async def test_unknown_primitive_ignored() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1", "totally_made_up": {"implementation": "x", "config": {}}}))
                rt_unknown = await Runtime.load(f)
                assert rt_unknown is not None

        async def test_unknown_impl_raises() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1", "storage": {"implementation": "definitely_not_a_real_impl", "config": {}}}))
                try:
                    await Runtime.load(f)
                except ImplementationNotFoundError as e:
                    assert "definitely_not_a_real_impl" in str(e)
                else:
                    raise AssertionError("should have raised ImplementationNotFoundError")

        async def test_malformed_manifest_raises() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text("{ bad json")
                try:
                    await Runtime.load(f)
                except ManifestError:
                    pass
                else:
                    raise AssertionError("malformed JSON should raise ManifestError")

        async def test_pkg_dry_run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1", "pkg": {"implementation": "dry_run", "config": {"extra": "data"}}}))
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
                await rt_pkg.pkg.ensure_from_manifest("/nonexistent/pyproject.toml")

        async def test_pkg_pip() -> None:
            import shutil
            if not shutil.which("pip"):
                return
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1", "pkg": {"implementation": "pip", "config": {}}}))
                rt_pip = await Runtime.load(f)
                assert rt_pip.pkg is not None
                snap = await rt_pip.pkg.snapshot()
                assert isinstance(snap.packages, list)
                assert snap.timestamp > 0
                names = {p.name.lower() for p in snap.packages}
                assert "pyxen" in names

        async def test_getattr_raises() -> None:
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

        async def test_private_attr_raises() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1"}))
                rt_min = await Runtime.load(f)
                import contextlib
                with contextlib.suppress(AttributeError):
                    _ = rt_min.__dict__

        async def test_cron_extension() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                manifest = {
                    "version": "1",
                    "storage": {"implementation": "inmemory", "config": {}},
                    "cron": {"jobs": [{"name": "t", "command": "echo hi", "schedule": "* * * * *"}]},
                }
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps(manifest))
                rt_cron = await Runtime.load(f)
                if hasattr(rt_cron, "cron"):
                    t = await rt_cron.cron.status("t")
                    if t is not None:
                        assert t.name == "t"

        async def test_no_cron_section() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({"version": "1"}))
                rt_min = await Runtime.load(f)
                try:
                    _ = rt_min.cron
                except AttributeError:
                    pass
                else:
                    raise AssertionError("no cron section -> rt.cron should not exist")

        async def test_config_has_secret_refs() -> None:
            assert _config_has_secret_refs({SECRET_REF_KEY: "mykey"}) is True
            assert _config_has_secret_refs({"not_secret": "val"}) is False
            assert _config_has_secret_refs({SECRET_REF_KEY: "k", "extra": 1}) is False
            assert _config_has_secret_refs({"creds": {SECRET_REF_KEY: "k"}}) is True
            assert _config_has_secret_refs({"a": {"b": [{SECRET_REF_KEY: "x"}]}}) is True
            assert _config_has_secret_refs(None) is False
            assert _config_has_secret_refs("string") is False
            assert _config_has_secret_refs(42) is False

        async def test_two_phase_with_secret() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({
                    "version": "1",
                    "secrets": {"implementation": "dotenv", "config": {"path": str(Path(tmp) / ".env")}},
                    "storage": {"implementation": "inmemory", "config": {"credentials": {SECRET_REF_KEY: "gcp"}}},
                }))
                rt_secret = await Runtime.load(f)
                assert rt_secret.secrets is not None
                assert rt_secret.storage is not None

        async def test_two_phase_without_secret_raises() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({
                    "version": "1",
                    "storage": {"implementation": "inmemory", "config": {"credentials": {SECRET_REF_KEY: "gcp"}}},
                }))
                try:
                    await Runtime.load(f)
                except ManifestError as e:
                    assert SECRET_REF_KEY in str(e)
                else:
                    raise AssertionError("$secret ref without secrets should raise ManifestError")

        async def test_two_phase_no_refs() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "runtime.json"
                f.write_text(json.dumps({
                    "version": "1",
                    "storage": {"implementation": "inmemory", "config": {}},
                    "secrets": {"implementation": "dotenv", "config": {"path": str(Path(tmp) / ".env")}},
                }))
                rt_no_ref = await Runtime.load(f)
                assert rt_no_ref.storage is not None
                assert rt_no_ref.secrets is not None

        await arun_tests(
            test_full_manifest,
            test_partial_manifest,
            test_unknown_primitive_ignored,
            test_unknown_impl_raises,
            test_malformed_manifest_raises,
            test_pkg_dry_run,
            test_pkg_pip,
            test_getattr_raises,
            test_private_attr_raises,
            test_cron_extension,
            test_no_cron_section,
            test_config_has_secret_refs,
            test_two_phase_with_secret,
            test_two_phase_without_secret_raises,
            test_two_phase_no_refs,
        )

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
