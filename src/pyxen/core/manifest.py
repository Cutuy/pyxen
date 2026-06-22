"""runtime.json schema and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._paths import project_path
from .errors import ManifestError

MANIFEST_SCHEMA = project_path("schemas", "runtime.schema.json")

SECRET_REF_KEY = "$secret"
PRIMITIVE_NAMES: tuple[str, ...] = (
    "identity",
    "tokens",
    "ipc",
    "pkg",
    "storage",
    "secrets",
    "observability",
)

# Extension names known to the manifest. The raw config section for each is
# stored in ``Manifest.extensions`` and passed to the extension's ``init()``.
EXTENSION_NAMES: tuple[str, ...] = ("cron",)


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
    extensions: dict[str, Any]  # extension name → raw config section

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


def _config_has_secret_refs(config: object) -> bool:
    if isinstance(config, dict):
        keys = list(config.keys())
        if keys == [SECRET_REF_KEY] and isinstance(config.get(SECRET_REF_KEY), str):
            return True
        return any(_config_has_secret_refs(v) for v in config.values())
    if isinstance(config, list):
        return any(_config_has_secret_refs(item) for item in config)
    return False


def parse_manifest(raw: dict[str, Any]) -> Manifest:
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

    # Check for $secret refs in any binding config
    has_secret_refs = False
    for binding in bindings.values():
        if _config_has_secret_refs(binding.config):
            has_secret_refs = True
            break
    if has_secret_refs and "secrets" not in bindings:
        raise ManifestError(
            f"config references {SECRET_REF_KEY} but no secrets primitive declared"
        )

    extensions: dict[str, Any] = {}
    for ext_name in EXTENSION_NAMES:
        section = raw.get(ext_name)
        if section is not None:
            if not isinstance(section, dict):
                raise ManifestError(
                    f"manifest section '{ext_name}' must be a JSON object"
                )
            extensions[ext_name] = section

    return Manifest(
        version=raw["version"],
        bindings=bindings,
        raw=raw,
        extensions=extensions,
    )


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

    # --- SCHEMA path points to the JSON file ---
    assert MANIFEST_SCHEMA.is_file()
    schema_content = json.loads(MANIFEST_SCHEMA.read_text())
    assert schema_content["type"] == "object"

    # --- cron extension: absent → empty dict ---
    m_no_ext = parse_manifest({"version": "1"})
    assert m_no_ext.extensions == {}

    # --- cron extension: present → stored in extensions dict ---
    m_ext = parse_manifest({
        "version": "1",
        "cron": {
            "jobs": [
                {"name": "backup", "command": "/usr/bin/backup.sh", "schedule": "0 3 * * *"},
                {"name": "heartbeat", "command": "curl -s https://example.com", "schedule": "*/5 * * * *", "enabled": True, "environment": {"PATH": "/usr/bin"}},
                {"name": "cleanup", "command": "rm -rf /tmp/*", "schedule": "@daily"},
            ]
        }
    })
    assert "cron" in m_ext.extensions
    cron_section = m_ext.extensions["cron"]
    assert len(cron_section["jobs"]) == 3

    # --- Extension section: non-object raises ---
    try:
        parse_manifest({"version": "1", "cron": "bad"})
    except ManifestError as e:
        assert "cron" in str(e)
    else:
        raise AssertionError("non-object extension section should raise ManifestError")

    # --- frozen Manifest including extensions ---
    assert m_ext.extensions["cron"]["jobs"][0]["name"] == "backup"
    try:
        m_ext.extensions = {}  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("Manifest should be frozen")

    # --- _config_has_secret_refs top-level ---
    assert _config_has_secret_refs({SECRET_REF_KEY: "mykey"}) is True
    assert _config_has_secret_refs({"not_secret": "val"}) is False
    assert _config_has_secret_refs({SECRET_REF_KEY: "k", "extra": 1}) is False

    # --- _config_has_secret_refs nested in dict ---
    assert _config_has_secret_refs({"creds": {SECRET_REF_KEY: "k"}}) is True
    assert _config_has_secret_refs({"a": {"b": {"c": {SECRET_REF_KEY: "deep"}}}}) is True

    # --- _config_has_secret_refs in list ---
    assert _config_has_secret_refs([{SECRET_REF_KEY: "k"}]) is True
    assert _config_has_secret_refs([1, "str", {"nested": [{SECRET_REF_KEY: "x"}]}]) is True

    # --- _config_has_secret_refs non-dict/non-list ---
    assert _config_has_secret_refs("plain string") is False
    assert _config_has_secret_refs(None) is False
    assert _config_has_secret_refs(42) is False

    # --- $secret ref without secrets primitive raises ManifestError ---
    try:
        parse_manifest({
            "version": "1",
            "storage": {
                "implementation": "bq",
                "config": {"credentials": {SECRET_REF_KEY: "gcp"}},
            },
        })
    except ManifestError as e:
        assert SECRET_REF_KEY in str(e)
    else:
        raise AssertionError("$secret ref without secrets should raise ManifestError")

    # --- $secret ref with secrets primitive succeeds ---
    m_ok = parse_manifest({
        "version": "1",
        "storage": {
            "implementation": "bq",
            "config": {"credentials": {SECRET_REF_KEY: "gcp"}},
        },
        "secrets": {"implementation": "dotenv", "config": {}},
    })
    assert "secrets" in m_ok.bindings
    assert "storage" in m_ok.bindings


if __name__ == "__main__":
    _main()
