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
    import os
    import tempfile
    from pathlib import Path

    if shutil.which("uv") is None:
        from pyxen._testlib import skip
        skip("uv not on PATH")
        return

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        impl = build({})
        try:
            async def test_snapshot_returns_list() -> None:
                snap = await impl.snapshot()
                assert isinstance(snap.packages, list)
                assert snap.timestamp > 0

            async def test_pyxen_in_names() -> None:
                snap = await impl.snapshot()
                names = {p.name.lower() for p in snap.packages}
                assert "pyxen" in names, f"pyxen not in uv pip list: {names}"

            async def test_package_info_shape() -> None:
                snap = await impl.snapshot()
                for pkg in snap.packages:
                    assert isinstance(pkg.name, str) and pkg.name
                    assert isinstance(pkg.version, str) and pkg.version
                    assert pkg.source == "uv"

            async def test_ensure_python_empty() -> None:
                await impl.ensure_python([])

            async def test_ensure_from_manifest_missing() -> None:
                await impl.ensure_from_manifest("/nonexistent/requirements.txt")

            async def test_parse_requirements_comments_and_extras() -> None:
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

            async def test_parse_requirements_plain_exact_min() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "reqs2.txt"
                    f.write_text("requests\nflask==3.0.0\ndjango>=5.0\n")
                    parsed2 = UvPkg._parse_requirements(f)
                    assert parsed2 == ["requests", "flask", "django"], parsed2

            async def test_parse_requirements_whitespace_inline_comment() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "reqs3.txt"
                    f.write_text("  numpy >= 2.0  \n  # inline comment\ntorch\n")
                    parsed3 = UvPkg._parse_requirements(f)
                    assert parsed3 == ["numpy", "torch"], parsed3

            async def test_parse_requirements_empty_file() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "empty.txt"
                    f.write_text("")
                    parsed4 = UvPkg._parse_requirements(f)
                    assert parsed4 == [], parsed4

            async def test_verify_checks_installed() -> None:
                result = await impl.verify()
                assert isinstance(result.satisfied, bool)

            async def test_verify_nonexistent_file() -> None:
                impl_none = build({"requirements": "/nonexistent/requirements.txt"})
                result_none = await impl_none.verify()
                assert result_none.satisfied

            async def test_verify_with_real_file() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    req_path = Path(tmp) / "requirements.txt"
                    req_path.write_text("pyxen\n")
                    impl_tmp = build({"requirements": str(req_path)})
                    result_tmp = await impl_tmp.verify()
                    assert result_tmp.satisfied, f"pyxen should be installed: missing={result_tmp.missing}"

            async def test_verify_detects_missing_package() -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    req_path = Path(tmp) / "missing_req.txt"
                    req_path.write_text("completely_nonexistent_package_xyz\n")
                    impl_missing = build({"requirements": str(req_path)})
                    result_missing = await impl_missing.verify()
                    assert result_missing.satisfied is False
                    assert "completely_nonexistent_package_xyz" in result_missing.missing

            async def test_install_tests() -> None:
                if os.environ.get("PYXEN_UV_INSTALL_TEST"):
                    await impl.ensure_python(["six"])
                    snap2 = await impl.snapshot()
                    names2 = {p.name.lower() for p in snap2.packages}
                    assert "six" in names2, f"six should be installed: {names2}"

                    with tempfile.TemporaryDirectory() as tmp:
                        req_path = Path(tmp) / "requirements.txt"
                        req_path.write_text("six\n")
                        await impl.ensure_from_manifest(str(req_path))

            await arun_tests(
                test_snapshot_returns_list,
                test_pyxen_in_names,
                test_package_info_shape,
                test_ensure_python_empty,
                test_ensure_from_manifest_missing,
                test_parse_requirements_comments_and_extras,
                test_parse_requirements_plain_exact_min,
                test_parse_requirements_whitespace_inline_comment,
                test_parse_requirements_empty_file,
                test_verify_checks_installed,
                test_verify_nonexistent_file,
                test_verify_with_real_file,
                test_verify_detects_missing_package,
                test_install_tests,
            )
        finally:
            pass

    asyncio.run(_run_tests())

    def test_bad_config() -> None:
        impl_bad = build({"uv_path": "/nonexistent/uv"})
        assert isinstance(impl_bad, UvPkg)

    from pyxen._testlib import run_tests
    run_tests(test_bad_config)


if __name__ == "__main__":
    _main()
