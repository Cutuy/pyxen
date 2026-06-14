"""runtime.json schema and loader.

The manifest is the single environment-definition artifact. It maps each
primitive to a concrete implementation with its own configuration. The app
never touches it at import time; ``Runtime.load()`` reads it at startup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestError

# A minimal but extensible JSON Schema for runtime.json.
# Implementations may add their own config keys; the schema is intentionally
# permissive at the implementation-config level.
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "pyxen runtime config",
    "type": "object",
    "required": ["version"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "pattern": r"^\d+$"},
        "identity": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "tokens": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "ipc": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "pkg": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "storage": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "secrets": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
        "observability": {
            "type": "object",
            "required": ["implementation"],
            "properties": {
                "implementation": {"type": "string"},
                "config": {"type": "object"},
            },
        },
    },
}

PRIMITIVE_NAMES: tuple[str, ...] = (
    "identity",
    "tokens",
    "ipc",
    "pkg",
    "storage",
    "secrets",
    "observability",
)


@dataclass(frozen=True)
class PrimitiveBinding:
    """A single primitive's implementation + config from the manifest."""

    name: str
    implementation: str
    config: dict[str, Any]


@dataclass(frozen=True)
class Manifest:
    """Parsed, validated runtime.json manifest."""

    version: str
    bindings: dict[str, PrimitiveBinding]
    raw: dict[str, Any]

    def get(self, primitive: str) -> PrimitiveBinding:
        """Return the binding for ``primitive`` or raise ``ManifestError``."""
        binding = self.bindings.get(primitive)
        if binding is None:
            raise ManifestError(
                f"manifest is missing a binding for primitive '{primitive}'"
            )
        return binding


def load_manifest(path: str | Path) -> Manifest:
    """Load and validate a ``runtime.json`` from disk.

    Raises ``ManifestError`` on missing file, invalid JSON, or schema mismatch.
    """
    p = Path(path)
    if not p.is_file():
        raise ManifestError(f"runtime.json not found at {p}")

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"runtime.json at {p} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(f"runtime.json at {p} must be a JSON object, got {type(raw)}")

    return parse_manifest(raw)


def parse_manifest(raw: dict[str, Any]) -> Manifest:
    """Parse and validate a manifest dict (already loaded from JSON).

    Schema validation is intentionally light: we check the top-level shape
    and that any declared primitive binding has both an implementation name
    and a config object. Implementations are free to add their own config
    keys; the schema doesn't try to enumerate them.
    """
    if "version" not in raw:
        raise ManifestError("manifest is missing required field 'version'")
    if not isinstance(raw["version"], str):
        raise ManifestError("manifest field 'version' must be a string")

    bindings: dict[str, PrimitiveBinding] = {}
    for primitive in PRIMITIVE_NAMES:
        if primitive not in raw:
            continue
        section = raw[primitive]
        if not isinstance(section, dict):
            raise ManifestError(
                f"manifest section '{primitive}' must be a JSON object"
            )
        impl = section.get("implementation")
        if not isinstance(impl, str) or not impl:
            raise ManifestError(
                f"manifest section '{primitive}' is missing a string 'implementation'"
            )
        config = section.get("config", {})
        if not isinstance(config, dict):
            raise ManifestError(
                f"manifest section '{primitive}' has non-object 'config'"
            )
        bindings[primitive] = PrimitiveBinding(
            name=primitive,
            implementation=impl,
            config=config,
        )

    return Manifest(version=raw["version"], bindings=bindings, raw=raw)


def _main() -> None:
    """Test entry point for this module. Covers the manifest parser thoroughly."""
    import tempfile
    from pathlib import Path

    # --- Minimal valid manifest ---
    m = parse_manifest({"version": "1"})
    assert m.version == "1"
    assert m.bindings == {}
    assert m.raw == {"version": "1"}

    # --- Full manifest with all 7 primitives ---
    raw = {
        "version": "1",
        "identity": {"implementation": "env", "config": {}},
        "tokens": {"implementation": "json_budget", "config": {"path": "/tmp/b.json"}},
        "ipc": {"implementation": "inproc", "config": {}},
        "pkg": {"implementation": "dry_run", "config": {}},
        "storage": {"implementation": "inmemory", "config": {}},
        "secrets": {"implementation": "dotenv", "config": {"path": "/tmp/.env"}},
        "observability": {"implementation": "stdout", "config": {"level": "info"}},
    }
    m_full = parse_manifest(raw)
    assert m_full.version == "1"
    assert len(m_full.bindings) == 7
    assert m_full.get("storage").implementation == "inmemory"
    assert m_full.get("storage").config == {}
    assert m_full.get("tokens").config == {"path": "/tmp/b.json"}

    # --- Missing version ---
    try:
        parse_manifest({"storage": {"implementation": "x", "config": {}}})
    except ManifestError as e:
        assert "version" in str(e).lower()
    else:
        raise AssertionError("should have raised ManifestError")

    # --- Non-string version ---
    try:
        bad: dict[str, object] = {"version": 42}
        parse_manifest(bad)
    except ManifestError:
        pass
    else:
        raise AssertionError("should have raised on non-string version")

    # --- Missing implementation string ---
    try:
        parse_manifest({"version": "1", "storage": {"config": {}}})
    except ManifestError as e:
        assert "implementation" in str(e)
    else:
        raise AssertionError("should have raised on missing implementation")

    # --- Non-string implementation ---
    try:
        parse_manifest({"version": "1", "storage": {"implementation": 42, "config": {}}})
    except ManifestError:
        pass
    else:
        raise AssertionError("should have raised on non-string implementation")

    # --- Empty implementation string ---
    try:
        parse_manifest({"version": "1", "storage": {"implementation": "", "config": {}}})
    except ManifestError:
        pass
    else:
        raise AssertionError("should have raised on empty implementation")

    # --- Non-object section ---
    try:
        parse_manifest({"version": "1", "storage": "not a dict"})
    except ManifestError:
        pass
    else:
        raise AssertionError("should have raised on non-object section")

    # --- Non-object config ---
    try:
        parse_manifest({"version": "1", "storage": {"implementation": "x", "config": "bad"}})
    except ManifestError:
        pass
    else:
        raise AssertionError("should have raised on non-object config")

    # --- Unknown primitives are silently ignored (forward-compat) ---
    m_unknown = parse_manifest(
        {"version": "1", "made_up_thing": {"implementation": "x", "config": {}}}
    )
    assert "made_up_thing" not in m_unknown.bindings
    assert len(m_unknown.bindings) == 0

    # --- Config defaults to empty dict when missing ---
    m_no_config = parse_manifest({"version": "1", "storage": {"implementation": "x"}})
    assert m_no_config.get("storage").config == {}

    # --- Manifest.get() raises for missing primitive ---
    try:
        m.get("storage")
    except ManifestError as e:
        assert "storage" in str(e)
    else:
        raise AssertionError("Manifest.get() should raise on missing primitive")

    # --- Manifest.get() returns the binding when present ---
    b = m_full.get("storage")
    assert b.name == "storage"
    assert b.implementation == "inmemory"
    assert b.config == {}

    # --- load_manifest from disk ---
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "runtime.json"
        f.write_text('{"version": "1", "identity": {"implementation": "env", "config": {}}}')
        m_loaded = load_manifest(f)
        assert m_loaded.version == "1"
        assert m_loaded.get("identity").implementation == "env"

    # --- load_manifest: missing file ---
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_manifest(Path(tmp) / "nope.json")
        except ManifestError as e:
            assert "not found" in str(e).lower() or "nope" in str(e)
        else:
            raise AssertionError("load_manifest should raise on missing file")

    # --- load_manifest: invalid JSON ---
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "bad.json"
        f.write_text("{ this is not json")
        try:
            load_manifest(f)
        except ManifestError as e:
            assert "JSON" in str(e) or "json" in str(e)
        else:
            raise AssertionError("load_manifest should raise on invalid JSON")

    # --- load_manifest: top-level not a dict ---
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "list.json"
        f.write_text("[1, 2, 3]")
        try:
            load_manifest(f)
        except ManifestError:
            pass
        else:
            raise AssertionError("load_manifest should raise on non-object JSON")

    # --- PRIMITIVE_NAMES contains all 7 ---
    assert set(PRIMITIVE_NAMES) == {
        "identity",
        "tokens",
        "ipc",
        "pkg",
        "storage",
        "secrets",
        "observability",
    }

    # --- SCHEMA is a valid JSON Schema dict ---
    assert SCHEMA["type"] == "object"
    assert "version" in SCHEMA["required"]
    assert set(SCHEMA["properties"].keys()) >= set(PRIMITIVE_NAMES)


if __name__ == "__main__":
    _main()
