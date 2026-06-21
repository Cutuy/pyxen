# pyxen — write once, deploy anywhere

A 7-primitive userland runtime for portable Python apps. Read the full reference first:

- **`pyxen/README.md`** — all 7 primitives, method signatures, implementations, CLI, examples.
- **`pyxen/examples/`** — runnable apps (hello_runtime, data_pipeline, notes_app, a2a_chat).
- **`pyxen/docs/userland-runtime.md`** — design rationale.

## Core rule

**Route every environment-shaped concern through `rt.*`, never through OS, cloud, or SDK APIs directly.**

```python
rt = await Runtime.load("runtime.json")
await rt.storage.put(...)
await rt.identity.current()
async with rt.observability.trace(...) as span:
    ...
```

Validate: `pyxen validate runtime.json` then `pyxen doctor runtime.json`.

`pip install pyxen` — see README for full API.
