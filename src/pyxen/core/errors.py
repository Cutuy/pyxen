"""Common error types raised by the runtime and its primitives."""

from __future__ import annotations


class PyxenError(Exception):
    """Base class for all pyxen errors."""


class ManifestError(PyxenError):
    """Raised when the runtime.json manifest is malformed or cannot be loaded."""


class ImplementationNotFoundError(PyxenError):
    """Raised when a primitive is requested but no matching implementation is registered."""


class IdentityError(PyxenError):
    """Raised by identity primitives when authentication or lookup fails."""


class TokenBudgetExceeded(PyxenError):
    """Raised by tokens primitives when a budget check fails or charge is rejected."""


class StorageError(PyxenError):
    """Raised by storage primitives on read/write failures."""


class IPCError(PyxenError):
    """Raised by ipc primitives on send/receive failures."""


class PkgError(PyxenError):
    """Raised by pkg primitives when dependency resolution fails."""


class SecretsError(PyxenError):
    """Raised by secrets primitives when a credential lookup fails."""


class ObservabilityError(PyxenError):
    """Raised by observability primitives when telemetry emission fails."""


class ExtensionError(PyxenError):
    """Raised when a runtime extension cannot be loaded or initialized."""
