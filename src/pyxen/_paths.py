from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def project_root() -> Path:
    """Walk up from this module until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("could not find project root (no pyproject.toml found)")


def project_path(*parts: str) -> Path:
    """Resolve a path relative to the project root."""
    return project_root().joinpath(*parts)
