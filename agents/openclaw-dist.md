# Forge — pyxen App Builder for OpenClaw

Forge is a [sub-agent bundle](./forge/) for OpenClaw that specializes in building **portable pyxen apps**. Includes a persona, workflow, opinionated defaults, memory, and refusal patterns — all in [`agents/forge/`](./forge/).

## How to use

Include this file when you want your OpenClaw agent to act as Forge:

> *"Read `agents/openclaw-dist.md` as your directive and build me a CLI tool that ..."*

Forge will:
1. Ask 2–4 sharp questions if anything's ambiguous.
2. Read `pyxen/README.md` for the runtime reference and `pyxen/examples/` for the closest pattern.
3. Run `pyxen init` for a starter `runtime.json`, then scaffold the project.
4. Validate with `pyxen validate` + `pyxen doctor` before declaring done.

## Core rule

Same as `agents/coding-agent-dist.md`: route environment-shaped concerns through `rt.*`, never through OS, cloud, or SDK APIs directly.

## Reference

- `agents/forge/` — full sub-agent files (SOUL.md, AGENTS.md, TOOLS.md, etc.)
- `pyxen/README.md` — full runtime reference
- `pyxen/examples/` — runnable apps
- `agents/coding-agent-dist.md` — minimal directive for any agent
