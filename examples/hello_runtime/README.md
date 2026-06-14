# hello_runtime

The proof-of-life example. The smallest thing that exercises the runtime end-to-end:

- Loads `runtime.json` (this directory)
- Calls `rt.identity.current()` to get the current user
- Writes a record via `rt.storage`
- Reads it back
- Emits a single trace via `rt.observe`
- Prints one line

## Run

From the repo root:

```bash
PYTHONPATH=src python examples/hello_runtime/main.py
```

Expected output (with the default config — `env` identity, `inmemory` storage, `stdout` observability):

```json
{"event": "span_start", "span": "hello-runtime"}
{"event": "log", "span": "hello-runtime", "level": "info", "message": "wrote greeting", "key": "world"}
{"event": "span_end", "span": "hello-runtime", "attributes": {"user": "..."}, "error": null}
hi from anonymous; storage said: {'message': 'hello, runtime', 'from': 'anonymous'}
```

The `anonymous` identity is what the `env` impl falls back to when `PYXEN_IDENTITY_ID` is not set.
