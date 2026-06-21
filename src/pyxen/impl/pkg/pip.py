"""``pip`` pkg impl — delegates to ``pip`` for lock-file-first dependency
satisfaction.

Reads a ``requirements.txt`` (or any pip-compatible lock file) and uses
``pip install -r`` for ``ensure()``. ``snapshot()`` and ``verify()`` use
``pip list --format=json``.

Config shape (in ``runtime.json``):

    {
      "implementation": "pip",
      "config": {
        "requirements": "requirements.txt",
        "python": "python3"
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
    logger.debug("pkg[pip] running: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
    except FileNotFoundError as exc:
        raise PkgError(f"pkg[pip]: command not found: {cmd[0]}") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise PkgError(
            f"pkg[pip]: command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )
    return stdout.decode()


class PipPkg:
    """pip-backed pkg implementation. Reads a requirements file and delegates
    to pip for installs, listing, and verification."""

    def __init__(self, config: dict[str, object]) -> None:
        self._config = config
        self._requirements = Path(str(config.get("requirements", "requirements.txt")))
        self._python = str(config.get("python", "python3"))

    # ---- protocol surface ----

    async def ensure(self) -> Snapshot:
        """Install deps via ``pip install -r`` and return current snapshot."""
        if not self._requirements.is_file():
            logger.info("pkg[pip]: %s not present, ensure() is a no-op", self._requirements)
            return await self.snapshot()
        await _run(["pip", "install", "-r", str(self._requirements), "--quiet"])
        return await self.snapshot()

    async def snapshot(self) -> Snapshot:
        """Return the current resolved state via ``pip list --format=json``."""
        stdout = await _run(["pip", "list", "--format=json"])
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PkgError(f"pkg[pip]: could not parse pip list output: {exc}") from exc
        packages = [
            PackageInfo(name=p["name"], version=p["version"], source="pip")
            for p in data
            if isinstance(p, dict) and "name" in p and "version" in p
        ]
        return Snapshot(packages=packages, timestamp=time.time())

    async def verify(self) -> VerificationResult:
        """Check every top-level requirement against installed packages.

        Parses the requirements file for package names, then checks each
        against the output of ``pip list --format=json``.
        """
        if not self._requirements.is_file():
            snap = await self.snapshot()
            return VerificationResult(satisfied=True, missing=[])

        installed_stdout = await _run(["pip", "list", "--format=json"])
        try:
            installed_data = json.loads(installed_stdout)
        except json.JSONDecodeError as exc:
            raise PkgError(f"pkg[pip]: could not parse pip list output: {exc}") from exc

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
        await _run(["pip", "install", "--quiet", *requirements])

    async def ensure_from_manifest(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            logger.info("pkg[pip]: manifest %s not present, skipping", path)
            return
        await _run(["pip", "install", "-r", str(p), "--quiet"])

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


def build(config: dict[str, object]) -> PipPkg:
    return PipPkg(config)


def _main() -> None:
    """Test entry point for pip pkg impl. Smoke-tests build + ensure paths.
    Skips if pip is not available on PATH."""
    import asyncio
    import os
    import tempfile

    if shutil.which("pip") is None:
        logger.info("pip not on PATH; skipping pip pkg tests")
        return

    async def go() -> None:
        # Build with empty config — defaults to requirements.txt
        impl = build({})
        snap = await impl.snapshot()
        assert isinstance(snap.packages, list)
        assert snap.timestamp > 0
        # pyxen itself should be installed in the dev venv
        names = {p.name.lower() for p in snap.packages}
        assert "pyxen" in names, f"pyxen not in pip list: {names}"

        # Snapshot returns PackageInfo with name, version, source
        for pkg in snap.packages:
            assert isinstance(pkg.name, str) and pkg.name
            assert isinstance(pkg.version, str) and pkg.version
            assert pkg.source == "pip"

        # ensure_python with empty list is a no-op
        await impl.ensure_python([])

        # ensure_from_manifest on a missing file is a no-op
        await impl.ensure_from_manifest("/nonexistent/requirements.txt")

        # _parse_requirements: comments, blank lines, -r includes, extras, comparisons
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
            parsed = PipPkg._parse_requirements(f)
            assert parsed == ["numpy", "pandas", "httpx"], parsed

        # _parse_requirements: plain name, exact version, min version
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reqs2.txt"
            f.write_text("requests\nflask==3.0.0\ndjango>=5.0\n")
            parsed2 = PipPkg._parse_requirements(f)
            assert parsed2 == ["requests", "flask", "django"], parsed2

        # _parse_requirements: mixed whitespace, inline comment
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reqs3.txt"
            f.write_text("  numpy >= 2.0  \n  # inline comment\ntorch\n")
            parsed3 = PipPkg._parse_requirements(f)
            assert parsed3 == ["numpy", "torch"], parsed3

        # _parse_requirements: empty file
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "empty.txt"
            f.write_text("")
            parsed4 = PipPkg._parse_requirements(f)
            assert parsed4 == [], parsed4

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

        # verify() that detects a missing package
        with tempfile.TemporaryDirectory() as tmp:
            req_path = Path(tmp) / "missing_req.txt"
            req_path.write_text("completely_nonexistent_package_xyz\n")
            impl_missing = build({"requirements": str(req_path)})
            result_missing = await impl_missing.verify()
            assert result_missing.satisfied is False
            assert "completely_nonexistent_package_xyz" in result_missing.missing

        # ensure_python and ensure_from_manifest with real install (skip unless env var set)
        if os.environ.get("PYXEN_PIP_INSTALL_TEST"):
            await impl.ensure_python(["six"])
            snap2 = await impl.snapshot()
            names2 = {p.name.lower() for p in snap2.packages}
            assert "six" in names2, f"six should be installed: {names2}"

            with tempfile.TemporaryDirectory() as tmp:
                req_path = Path(tmp) / "requirements.txt"
                req_path.write_text("six\n")
                await impl.ensure_from_manifest(str(req_path))

    asyncio.run(go())

    # Bad config doesn't raise (empty dict is valid)
    impl_bad = build({"python": "/nonexistent/python"})
    assert isinstance(impl_bad, PipPkg)


if __name__ == "__main__":
    _main()
