# HEARTBEAT.md — Periodic Checks

_I'm a build-on-demand agent, not an always-on monitor. But a few checks keep me sharp._

## Weekly (when heartbeat fires)

- **pyxen release check** — `pip index versions pyxen 2>&1 | head -3`. If a new version dropped, run `pyxen init` against a fresh dir and diff against the previous starter manifest. If the schema or default impls changed, update `MEMORY.md` "pyxen version tracking."
- **Reference examples sanity** — read `pyxen/examples/notes_app/` and `pyxen/examples/hello_runtime/` to confirm the patterns I lean on are still current. If the library maintainer restructured them, update my approach.
- **Optional-dep review** — confirm the optional groups my apps rely on (`openai`, `cloud`, `a2a`, `examples`) are still installable. `pip install "pyxen[examples]" --dry-run` in a fresh venv.

## Per-build (after each app shipped)

- Update `MEMORY.md` "Apps built" table.
- Update `MEMORY.md` "Reference patterns I've leaned on" with which `pyxen/examples/` pattern was adapted.
- Update `MEMORY.md` "Patterns that worked" / "Gotchas to avoid" if anything new came up.
- Append a session log to `memory/YYYY-MM-DD.md`.

## When to reach out to the user

- New pyxen release with breaking schema changes.
- Library bug I hit that the user should know about before their next build.
- Patterns the user might want to adopt (saw something clever in the pyxen repo, want to flag it).

## When to stay silent

- Routine version checks with no diff.
- Successful builds (the user already knows; logging is enough).
- Heartbeats during late-night hours when the user is asleep.

## Tracking state

Update `memory/heartbeat-state.json` with last check timestamps:

```json
{
  "lastChecks": {
    "pyxen_release": null,
    "reference_examples_drift": null,
    "optional_deps_installable": null
  }
}
```