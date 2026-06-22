# The Portable Runtime

A research note motivating the design of pyxen.

The most impactful layer is a *general-purpose* portable runtime that *any* application can link against.

## What it is

A library, a config file, a set of interfaces. No vendor lock. The runtime routes every environment-shaped call (`identity()`, `storage()`, `ipc()`, etc.) to a *provider* configured in `runtime.json`. Swap the config, swap the environment — no code changes. OpenAI's Agents SDK is not a wrapped backend; its individual pieces (Manifest, handoffs, tracing) are consumed per-primitive alongside non-OpenAI implementations.

```
┌─────────────────────────────────────────────────────────────┐
│  APPLICATION  — CLI · web · pipeline · w/ or w/o agents     │
│  rt = await Runtime.load("runtime.json")                    │
│  await rt.storage.put(...)  ·  await rt.identity.current()  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  PORTABLE RUNTIME  — 7 primitives                            │
│  identity · tokens · ipc · pkg · storage · secrets · observe │
└──────────────────────────┬──────────────────────────────────┘
                           │  runtime.json maps primitives → providers
┌──────────────────────────▼──────────────────────────────────┐
│  IMPL LAYER  — per-primitive impls (sqlite, keychain, pip,   │
│                openai_handoffs, otel, …)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  RAW ENVIRONMENT  — the machine, the cloud, the OS           │
└─────────────────────────────────────────────────────────────┘
```

The runtime is not a layer above agents or SDKs. It's the interface the *application* uses. The app shell and any embedded agents share one runtime. **Intertwined, not layered.**

## Prior art

Each of these captures one piece; none compose all seven:

- **WASI** — portable OS interface for Wasm
- **OpenAI Agents SDK** — Manifest abstraction for portable sandboxes
- **OpenHands SDK** — workspace abstraction
- **Agent Auth Protocol** — cryptographic per-agent identity
- **Microsoft Agent Framework 1.0** — tools decoupled from OS
- **Dagger Functions** — provider-swappable sandbox SDK
- **Nix** — declarative environments-as-code

> **The gap:** The Portable Runtime composes all seven behind a single `runtime.json`, consuming existing pieces rather than reimplementing them.

## The bet

By 2027 every serious agent runtime will have a provider-injection interface shaped like these 7 primitives. OS-level primitives will ship eventually, but **after** the runtime — because the runtime is faster to build, easier to adopt, and solves the portability problem enterprises are hitting *today*.

**The Bet:** Ship pyxen as a pip package. The 7 primitives are what apps actually need. When the OS catches up, the runtime uses it as a provider.
