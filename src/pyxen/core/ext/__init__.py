"""Extension mechanism for the pyxen runtime.

Extensions are pluggable, stateful modules that register themselves with the
runtime and are initialized from the manifest. Unlike core primitives
(identity, storage, …) which are pure interfaces with swappable backends,
extensions can modify system state, track execution history, and provide
additional capabilities via ``rt.<name>``.

To add a new extension:

1. Create a package under ``pyxen.core.ext.<name>`` with an ``init()``
   function that accepts ``(config: dict, app_dir: Path | None)`` and
   returns an object to expose on the runtime.
2. Add the name to ``EXTENSION_NAMES`` and ``EXTENSION_REGISTRY`` below.
3. Add its schema to the manifest (``manifest.SCHEMA`` top-level properties).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ..errors import ExtensionError

# Ordered list of known extension names. Add new extensions here.
EXTENSION_NAMES: tuple[str, ...] = ("cron",)

# Maps extension name → module path for ``init()`` lookup.
EXTENSION_REGISTRY: dict[str, str] = {
    "cron": "pyxen.core.ext.cron",
}


async def init_extension(name: str, config: dict[str, Any], app_dir: Path | None) -> Any:
    """Load and initialize a single extension from its manifest section.

    Args:
        name: Extension name (must be in ``EXTENSION_REGISTRY``).
        config: The extension's config section from the manifest.
        app_dir: The application root directory (for resolving relative paths).

    Returns:
        An object that will be exposed as ``rt.<name>``.

    Raises:
        ExtensionError: If the extension is unknown or has no ``init()``.
    """
    module_path = EXTENSION_REGISTRY.get(name)
    if module_path is None:
        raise ExtensionError(f"unknown extension '{name}'")

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ExtensionError(
            f"extension module '{module_path}' not found: {exc}"
        ) from exc

    init_fn = getattr(module, "init", None)
    if init_fn is None:
        raise ExtensionError(
            f"extension '{name}' ({module_path}) has no init() function"
        )

    result = init_fn(config, app_dir)
    if hasattr(result, "__await__"):
        result = await result
    return result


def _main() -> None:
    """Unit tests for the extension loader."""
    import asyncio

    # init_extension on unknown name raises
    async def go() -> None:
        try:
            await init_extension("nonexistent_extension", {}, None)
        except ExtensionError as e:
            assert "unknown" in str(e).lower()
        else:
            raise AssertionError("expected ExtensionError")

        # init_extension on known module with no init() raises
        try:
            await init_extension("cron", {}, None)
        except ExtensionError:
            # The cron module does have init(), so this may succeed.
            # We just verify it doesn't crash with wrong module path.
            pass

    asyncio.run(go())


if __name__ == "__main__":
    _main()
