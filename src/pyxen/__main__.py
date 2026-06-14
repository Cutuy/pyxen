"""Allow ``python -m pyxen`` to work as a CLI entry point.

Bridges to ``pyxen._cli.main()``, same as the script entry point
defined in ``pyproject.toml``.
"""

from __future__ import annotations

import sys

from pyxen._cli import main as _cli_main

sys.exit(_cli_main())
