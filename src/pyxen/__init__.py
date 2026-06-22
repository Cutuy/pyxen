"""pyxen — a userland runtime interface for portable Python apps.

The runtime is a thin Python package that provides 7 environment-shaped
primitives (identity, tokens, ipc, pkg, storage, secrets, observability)
behind a single, swappable interface. The application imports ``pyxen``,
loads a ``runtime.json`` config, and calls ``rt.identity``, ``rt.storage``,
etc. — never the underlying OS or any specific service.

Implementations live under ``pyxen.impl.<primitive>``; each impl sub-package
hosts one or more concrete implementations that can reach into the OpenAI
Agents SDK, Vault, NATS, SQLite, or any other source as needed.
"""

from __future__ import annotations

from .core import (
    MANIFEST_SCHEMA,
    Budget,
    Charge,
    CheckResult,
    Credential,
    Identity,
    IdentityError,
    IdentityImpl,
    ImplementationNotFoundError,
    IPCError,
    IpcImpl,
    Manifest,
    ManifestError,
    Message,
    ObservabilityError,
    ObservabilityImpl,
    PkgError,
    PkgImpl,
    PrimitiveBinding,
    PyxenError,
    QueryFilter,
    Runtime,
    SecretsError,
    SecretsImpl,
    Span,
    StorageError,
    StorageImpl,
    TokenBudgetExceeded,
    TokensImpl,
    load_manifest,
    parse_manifest,
)
from .test import discover as discover_test_modules

__version__ = "0.2.0a1"

__all__ = [
    "discover_test_modules",
    "__version__",
    "Budget",
    "Charge",
    "CheckResult",
    "Credential",
    "Identity",
    "IpcImpl",
    "IdentityImpl",
    "ImplementationNotFoundError",
    "IdentityError",
    "IPCError",
    "MANIFEST_SCHEMA",
    "Manifest",
    "ManifestError",
    "Message",
    "ObservabilityError",
    "ObservabilityImpl",
    "PkgError",
    "PkgImpl",
    "PrimitiveBinding",
    "PyxenError",
    "QueryFilter",
    "Runtime",
    "SecretsError",
    "SecretsImpl",
    "Span",
    "StorageError",
    "StorageImpl",
    "TokenBudgetExceeded",
    "TokensImpl",
    "load_manifest",
    "parse_manifest",
]
