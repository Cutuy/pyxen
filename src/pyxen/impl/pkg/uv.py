"""``uv`` pkg impl — delegates to ``uv`` for lock-file-first dependency
satisfaction.

Reads a ``requirements.txt`` (or any pip-compatible lock file) and uses
``uv pip sync`` for ``ensure()``. ``snapshot()`` and ``verify()`` use
``uv pip list --format=json``.

Config shape (in ``runtime.json``):

    {
      "implementation": "uv",
      "config": {
        "requirements": "requirements.txt",
        "uv_path": "uv"
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path

from ...core.errors import PkgError
from ...core.pkg import PackageInfo, Snapshot, VerificationResult

logger = logging.getLogger(__name__)


async def _run(cmd: list[str], cwd: Path | None = None) -> str:
    """Run a subprocess and return stdout. Raises PkgError on failure."""
    logger.debug("pkg[uv] running: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
    except FileNotFoundError as exc:
        raise PkgError(f"pkg[uv]: command not found: {cmd[0]}") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise PkgError(
            f"pkg[uv]: command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )
    return stdout.decode()


class UvPkg:
    """uv-backed pkg implementation. Reads a requirements file and delegates
    to uv for installs, listing, and verification."""

    def __init__(self, config: dict[str, object]) -> None:
        self._config = config
        self._requirements = Path(str(config.get("requirements", "requirements.txt")))
        self._uv = str(config.get("uv_path", "uv"))

    # ---- protocol surface ----

    async def ensure(self) -> Snapshot:
        """Install deps via ``uv pip sync`` and return current snapshot."""
        if not self._requirements.is_file():
            logger.info("pkg[uv]: %s not present, ensure() is a no-op", self._requirements)
            return await self.snapshot()
        await _run([self._uv, "pip", "sync", str(self._requirements)])
        return await self.snapshot()

    async def snapshot(self) -> Snapshot:
        """Return the current resolved state via ``uv pip list --format=json``."""
        stdout = await _run([self._uv, "pip", "list", "--format=json"])
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PkgError(f"pkg[uv]: could not parse uv pip list output: {exc}") from exc
        packages = [
            PackageInfo(name=p["name"], version=p["version"], source="uv")
            for p in data
            if isinstance(p, dict) and "name" in p and "version" in p
        ]
        return Snapshot(packages=packages, timestamp=time.time())

    async def verify(self) -> VerificationResult:
        """Check every top-level requirement against installed packages.

        Parses the requirements file for package names, then checks each
        against the output of ``uv pip list --format=json``.
        """
        if not self._requirements.is_file():
            snap = await self.snapshot()
            return VerificationResult(satisfied=True, missing=[])

        installed_stdout = await _run([self._uv, "pip", "list", "--format=json"])
        try:
            installed_data = json.loads(installed_stdout)
        except json.JSONDecodeError as exc:
            raise PkgError(f"pkg[uv]: could not parse uv pip list output: {exc}") from exc

        installed = {
            p["name"].lower(): p["version"]
            for p in installed_data
            if isinstance(p, dict) and "name" in p and "version" in p
        }

        missing: list[str] = []
        for name in self._parse_requirements(self._requirements):
            if name not in installed:
                missing.append(name)

        return VerificationResult(satisfied=not missing, missing=missing)

    # ---- legacy imperative helpers ----

    async def ensure_python(self, requirements: list[str]) -> None:
        if not requirements:
            return
        await _run([self._uv, "pip", "install", "--quiet", *requirements])

    async def ensure_from_manifest(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            logger.info("pkg[uv]: manifest %s not present, skipping", path)
            return
        await _run([self._uv, "pip", "install", "-r", str(p), "--quiet"])

    # ---- helpers ----

    @staticmethod
    def _parse_requirements(path: Path) -> list[str]:
        """Extract top-level package names from a pip requirements file.

        Handles ``name``, ``name==1.0``, ``name>=1.0``, ``name[extra]>=1.0``,
        and skips comments / blank lines / ``-r other.txt`` includes.
        """
        names: list[str] = []
        name_re = re.compile(r"^([A-Za-z0-9_.\-]+)")
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = name_re.match(line)
            if m:
                names.append(m.group(1).lower())
        return names


def build(config: dict[str, object]) -> UvPkg:
    return UvPkg(config)


def _main() -> None:
    """Test entry point for uv pkg impl. Smoke-tests build + ensure paths.
    Skips if uv is not available on PATH."""
    import asyncio
    import tempfile

    if shutil.which("uv") is None:
        logger.info("uv not on PATH; skipping uv pkg tests")
        return

    async def go() -> None:
        # Build with empty config — defaults to requirements.txt
        impl = build({})
        snap = await impl.snapshot()
        assert isinstance(snap.packages, list)
        assert snap.timestamp > 0
        # pyxen itself should be installed in the dev venv
        names = {p.name.lower() for p in snap.packages}
        assert "pyxen" in names, f"pyxen not in uv pip list: {names}"

        # ensure_python with empty list is a no-op
        await impl.ensure_python([])

        # ensure_from_manifest on a missing file is a no-op
        await impl.ensure_from_manifest("/nonexistent/requirements.txt")

        # _parse_requirements on a real-ish file
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reqs.txt"
            f.write_text(
                "# comment line\n"
                "\n"
                "numpy>=2.0\n"
                "pandas == 2.2.1\n"
                "httpx[socks]>=0.27\n"
                "-r other.txt\n"
            )
            parsed = UvPkg._parse_requirements(f)
            assert parsed == ["numpy", "pandas", "httpx"], parsed

        # verify() checks installed vs requirements
        result = await impl.verify()
        assert isinstance(result.satisfied, bool)

        # verify() with explicit non-existent requirements file
        impl_none = build({"requirements": "/nonexistent/requirements.txt"})
        result_none = await impl_none.verify()
        assert result_none.satisfied

        # verify() with a real requirements file in tmp dir
        with tempfile.TemporaryDirectory() as tmp:
            req_path = Path(tmp) / "requirements.txt"
            req_path.write_text("pyxen\n")
            impl_tmp = build({"requirements": str(req_path)})
            result_tmp = await impl_tmp.verify()
            assert result_tmp.satisfied, f"pyxen should be installed: missing={result_tmp.missing}"

    asyncio.run(go())

    # Bad config doesn't raise (empty dict is valid)
    impl_bad = build({"uv_path": "/nonexistent/uv"})
    assert isinstance(impl_bad, UvPkg)


if __name__ == "__main__":
    _main()
