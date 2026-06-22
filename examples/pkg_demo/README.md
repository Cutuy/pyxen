# pkg_demo

Demonstrates pyxen's **pkg** primitive — lock-file-first dependency
satisfaction from PyPI.

The example declares a single dependency (`requests`) in
`requirements.txt`. The `runtime.json` maps the `pkg` primitive to
the `pip` implementation, which reads that requirements file and
delegates to `pip install -r` on `ensure()`.

## The pattern

In a real deployment you'd:

1. List your Python dependencies in `requirements.txt` (or a pip-compatible
   lockfile).
2. Declare the `pkg` binding in `runtime.json` — no need to list each
   package individually:
   ```json
   "pkg": {
     "implementation": "pip",
     "config": {
       "requirements": "requirements.txt",
       "python": "python3"
     }
   }
   ```
3. Call `await rt.pkg.ensure()` at app startup (or rely on the runtime to
   call it automatically) to install anything missing.

Swap to `"implementation": "uv"` to use `uv pip sync` instead — zero
code changes outside `runtime.json`.

## Run

```bash
PYTHONPATH=src python examples/pkg_demo/main.py
```

Expected output (varies based on identity):

```
pkg ensured at t=1712345678; 12 packages resolved
verification: OK
hi from anonymous; fetched uuid=550e8400-e29b-41d4-a716-446655440000
```
