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

    async def go() -> None:
        impl = build({})

        # ensure_python is a no-op
        await impl.ensure_python(["numpy>=2.0", "pandas"])
        await impl.ensure_python([])  # empty list is fine

        # ensure_from_manifest on existing file is a no-op
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "pyproject.toml"
            f.write_text("[project]\nname = 'x'\n")
            await impl.ensure_from_manifest(str(f))

        # ensure_from_manifest on missing file is a no-op (logs and skips)
        await impl.ensure_from_manifest("/nonexistent/pyproject.toml")

    asyncio.run(go())


if __name__ == "__main__":
    _main()
