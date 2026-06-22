"""``dry_run`` pkg impl — no-op for environments where dependencies are
pre-installed.

This is the MVP-friendly default. In production, the ``pip`` impl (or the
``openai_manifest`` impl, which wraps the OpenAI Agents SDK's Manifest)
handles dependency resolution. For a dev laptop where the venv is already
set up, ``dry_run`` is enough.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DryRunPkg:
    """Records what would have been ensured, does nothing on disk."""

    def __init__(self, config: dict[str, object]) -> None:
        self._config = config

    async def ensure_python(self, requirements: list[str]) -> None:
        logger.info("dry_run pkg: would ensure python deps: %s", requirements)

    async def ensure_from_manifest(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            logger.info("dry_run pkg: manifest %s not present, skipping", path)
            return
        logger.info("dry_run pkg: would ensure deps from %s", path)


def build(config: dict[str, object]) -> DryRunPkg:
    return DryRunPkg(config)


def _main() -> None:
    """Test entry point for dry_run pkg impl. No-op behavior verified."""
    import asyncio
    import tempfile
    from pathlib import Path

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        impl = build({})
        try:
            async def test_ensure_python_with_deps() -> None:
                await impl.ensure_python(["numpy>=2.0", "pandas"])

            async def test_ensure_python_empty_list() -> None:
                await impl.ensure_python([])

            async def test_ensure_from_manifest_existing_file() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "pyproject.toml"
                    f.write_text("[project]\nname = 'x'\n")
                    await impl.ensure_from_manifest(str(f))

            async def test_ensure_from_manifest_missing_file() -> None:
                await impl.ensure_from_manifest("/nonexistent/pyproject.toml")

            await arun_tests(
                test_ensure_python_with_deps,
                test_ensure_python_empty_list,
                test_ensure_from_manifest_existing_file,
                test_ensure_from_manifest_missing_file,
            )
        finally:
            pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
