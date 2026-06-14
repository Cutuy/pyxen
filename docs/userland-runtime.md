# The Portable Userland

> A userland runtime interface for portable Python apps. The research note
> that motivates the design of this codebase.
>
> **Live visual deck:** [`userland-runtime.html`](./userland-runtime.html) ·
> **Companion:** [The Missing Kernel — Agent OS Primitives in 2026](https://github.com/Cutuy/harness-slides/blob/main/agent-frameworks/index.html) (a response to the latter's "agent framework" framing).
>
> **v0.3 revision (June 14, 2026):** Package structure is **per-primitive** (`impl/storage/`, `impl/identity/`, …) — not a top-level `impl/openai` vs `impl/local` split. Each primitive's impls can reach into OpenAI SDK pieces (or any other source) as needed. Working name: `pyxen`. Repo: private, personal org, GitHub Actions CI.

---

## The pivot

"The Missing Kernel" argued that the agent world needs 8 OS-level primitives. This deck argues the opposite: the most impactful layer isn't the kernel — it's a *general-purpose* userland runtime that *any* application can link against, regardless of whether that application contains agents.

The runtime isn't a layer above agents. It isn't a layer above OpenAI's Agents SDK. It is the **interface an application uses to talk to its environment** — including any agents embedded in that application. The app shell uses it. The agents inside use it. The boundary between them uses it. **Intertwined, not layered.**

> **The one-sentence pivot:** The Missing Kernel asks "what would `agent_fork(2)` look like?" This deck asks: **"what would an `npm install`-able runtime look like that makes the kernel primitive choice irrelevant to the application developer?"** The answer is a userland runtime that captures all environment-shaped concerns behind a stable, versioned, and swappable interface.

> **The relationship to OpenAI's Agents SDK:** The runtime is not a competitor to OpenAI's Agents SDK. It is the **interface**; OpenAI's SDK is one possible **backend** for several primitives (workspace, manifest, handoffs, storage mounts). The runtime can route `pkg` through an OpenAI Manifest, route `ipc` through OpenAI handoffs, route `secrets` through the SDK's env injection — while the same runtime also serves the app's non-agent code paths (UI, business logic, I/O). Same package, same primitives, same config. The SDK is a provider, not a layer.

| Dimension | The Missing Kernel | The Portable Userland |
|---|---|---|
| Primitives target | OS kernel (syscalls, kernel modules) | Package management (SDK, manifest, interface) |
| Integration | eBPF, FUSE, kernel patches, vendor SDKs | `pip install`, a `runtime.json` config |
| Portability mechanism | Same syscalls on every OS | Swappable providers per environment |
| Adoption barrier | Very high (kernel access needed, vendor lock) | Low (standard package integration) |
| Cloud port | Must recompile/re-vendor for cloud kernel | Swap `runtime.json` → same app runs |
| Fragmentation risk | Windows vs Linux vs macOS kernel APIs | Multi-environment, same runtime interface |

The two theses are complements, not competitors. Kernel primitives provide *isolation and enforcement*. Userland runtimes provide *portability and abstraction*. You need both. But if you have to pick which one to ship first, userland wins because it's immediately consumable by any application developer, on any machine, today.

---

## Why kernel primitives aren't enough

A thought experiment: suppose the 8 primitives are real Linux syscalls. Does it make your app portable?

Imagine tomorrow the Linux kernel adds `agent_fork(2)` and `agent_send(2)` and every Missing Kernel primitive exists at `syscall` level. Your app now uses `agent_fork(2)` for speculative execution. Great.

But your app still needs:

1. **An identity.** When it calls `github.createPR()`, whose token does it use? The kernel has no concept of a GitHub PAT or an OIDC token. Your app still needs a credential broker that lives in userland.
2. **A token budget.** Who decides the app gets $10/day? The kernel can *enforce* a cap (resource group), but the cap is configured per-deployment — the budget policy lives in userland config.
3. **Package dependencies.** Your agent needs to install `numpy`, `requests`, `playwright`. The kernel doesn't have a package manager. `apt` is userland. `npm` is userland. `pip` is userland.
4. **IPC routes.** Who is the agent allowed to talk to? The kernel knows packet routing; it doesn't know that "Codex Research Agent" is at `/agents/codex.sock`.
5. **Secrets / credentials.** The app needs its OpenAI API key. The kernel doesn't have a secrets store. Keychain is userland. Vault is userland.
6. **Observability sink.** Where do traces go? Langfuse? A local file? stdout? The kernel provides `perf_event_open(2)`; it doesn't know about OpenTelemetry endpoints.
7. **Storage backend.** Where does persistent state live? SQLite on disk? Postgres? S3? The kernel provides VFS; the binding to a specific storage provider is userland.

> **The insight:** Every single item in that list is **environment-shaped**. It differs between local, staging, and production. It differs between laptop and cloud. It differs between "Jason's workstation" and "someone else's OpenClaw instance." **The kernel can't fix this because the kernel doesn't know about application-level environment.** Only a userland runtime can.

---

## What is a userland runtime?

A library. A config file. A set of interfaces. That's it. No kernel patches, no FUSE, no vendor lock.

The **Portable Userland Runtime** is a single Python package that provides a small set of primitive interfaces. *Any* application imports it — not just agents. A web app imports it. A CLI imports it. A data pipeline imports it. An app that happens to contain one or more agents imports it for the app shell, the agent code, and the boundary between them. The runtime routes each call to a *provider* — a concrete implementation of the interface for the current environment.

An application built on this runtime is **naturally portable** because every environment-shaped interaction goes through the runtime. The application never knows whether identity comes from the macOS keychain or an OIDC provider. It never knows whether storage is SQLite on disk or Postgres in the cloud. It never knows whether its agents use OpenAI's SDK, Anthropic's SDK, or a local model. It just calls `runtime.identity()`, `runtime.storage()`, `runtime.ipc()`.

OpenAI's Agents SDK is not a wrapped *provider*. Its individual libraries (`SandboxClient`, `Manifest`, `handoffs`, `tracing`, `apply_patch`, `shell`) are sources of *primitive implementations*: `pkg` consumes `Manifest`, `secrets` consumes `Manifest.environment`, `ipc` consumes handoff semantics, and so on. The runtime can also draw on non-OpenAI pieces for the same primitive. **No single SDK is "the backend." Each primitive has implementations drawn from wherever they make sense.**

### The architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  PYTHON APPLICATION  — web app · CLI · data pipeline · w/ agents   │
│  from pyxen import Runtime                                            │
│  rt = await Runtime.load("runtime.json")                          │
│  me = await rt.identity.current()           # app shell          │
│  agent = await rt.agents.spawn(...)         # inside app        │
│  await rt.ipc.send(agent, msg)              # boundary          │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────────┐
│  USERLAND RUNTIME  — one Python interface, 7 primitives             │
│  identity · tokens · ipc · pkg · storage · secrets · observability │
└────────────────────────────────┬───────────────────────────────────┘
                                 │  runtime.json binds interfaces to implementations
┌────────────────────────────────▼───────────────────────────────────┐
│  IMPL LAYER  — per-primitive sub-packages; each impl can           │
│               reach into OpenAI SDK pieces (or any other source)   │
│  impl/storage/        ← local_sqlite · cloud_s3_via_openai_mounts │
│  impl/identity/       ← env · keychain · oidc · agent_auth_proto   │
│  impl/ipc/            ← unix_socket · openai_handoffs · nats      │
│  impl/pkg/            ← pip · openai_manifest · docker             │
│  impl/secrets/        ← dotenv · keychain · openai_env_injection   │
│  impl/observability/  ← stdout · otel · openai_tracing · langfuse  │
│  impl/tokens/         ← json_budget (runtime-native; no SDK piece)│
└────────────────────────────────┬───────────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────────┐
│  RAW ENVIRONMENT  — the machine, the cloud, the OS                │
└────────────────────────────────────────────────────────────────────┘
```

> **The runtime contract:** The runtime provides the interface. The config (`runtime.json`) maps interfaces to providers. The app never imports or configures providers directly. This is the separation that makes portability real: the app imports the runtime, and the runtime resolves at startup which providers to use based on the deployment environment.

### Intertwined, not layered

The runtime is **not** a layer above OpenAI's Agents SDK. It is not a layer above LangGraph, CrewAI, or AutoGen. It is the interface the application uses for environment-shaped concerns. When an app embeds an OpenAI agent, *the app and the agent both call the same runtime*:

```python
# App shell uses runtime for non-agent code paths
me = await rt.identity.current()
await rt.tokens.check("gpt-4o", 5000)

# App spawns an OpenAI agent (built from SDK pieces via the runtime)
agent = await rt.agents.spawn(
    model="gpt-5.5",
    manifest={"entries": {...}},        # OpenAI Manifest shape
    capabilities=["shell", "filesystem"],
)

# The agent's own code uses the SAME runtime primitives
# (same identity, same budget, same IPC routes)
agent_reply = await rt.ipc.send(agent, {"type": "do-work"})
```

The agent doesn't live in a different runtime. The app shell doesn't live in a different runtime. They share one. OpenAI's SDK pieces (`Manifest`, `SandboxClient`, `handoffs`, `tracing`) are consumed individually as primitive implementations — the runtime doesn't wrap the SDK as a single backend.

**But the MVP demos are agent-less apps.** The runtime's primary value is making *any* Python app portable. A CLI, a web app, a data pipeline — none of these need agents. The fact that an app *could* later host an agent (because someone embedded one, or because an agent generated the app in the first place) is a future benefit, not a v0 requirement. **The runtime is general-purpose; agents are an optional consumer.**

---

## The seven userland primitives

Each is an interface on the runtime object. Each has multiple implementations. Each captures one "environment fact" that differs between deployments.

### ① Identity — `runtime.identity`

> Replaces: hard-coded PAT loading, macOS keychain access, `$GITHUB_TOKEN` env vars, OIDC login scripts, credential files checked into repos.

The identity primitive answers: **who is this agent on behalf of?** It provides: the current user's ID, a set of delegated credentials, an authentication context (OAuth flow state, OIDC tokens), and a way to escalate or reauthenticate. The runtime handles credential lifecycle — refresh, rotation, expiry — transparently to the application.

**Providers:** macOS Keychain, OIDC (Google / Microsoft / GitHub), OAuth device flow, PKI certificate, `.env` file (dev only), HashiCorp Vault, Agent Identity Kit (portable DID-based identities).

### ② Token Usage & Limits — `runtime.tokens`

> Replaces: `maxTokens` in construction sites, `$OPENAI_KEY` env vars, app-level token budgets, manual cost tracking spreadsheets.

The token primitive is the userland **cgroup for AI costs**. It tracks token consumption, enforces budgets, and provides a check-before-spend interface. `rt.tokens.check(model, est)` returns `{ allowed, remaining, reason? }`. The runtime enforces the policy — if the budget is exhausted, the call fails with a clear error, not a surprise bill.

**Why this can't be a kernel primitive:** Token budgets are measured in *dollars and model-specific token counts*, not in CPU cycles. The kernel doesn't know what a "GPT-4o token" is.

**Providers:** Local JSON budget file, OpenClaw session budget, App-level quota manager, Langfuse spend tracking, API gateway rate-limit headers, Prometheus metrics.

### ③ IPC — `runtime.ipc`

> Replaces: HTTP between agents, A2A protocol, MCP client/server setup, Unix socket path hardcoding, message queue boilerplate.

The IPC primitive provides **agent-to-agent communication as a first-class runtime service**. One agent discovers another by name, sends a structured message, and receives a response (or subscribes to a stream). The runtime handles transport, addressing, serialization, backpressure, retry, and auth — the application just sends messages.

**Providers:** Unix socket (local), TCP with mutual TLS (network), NATS (cloud), Redis Pub/Sub, SQS (async), in-memory (same process), A2A-over-HTTP (interoperability).

### ④ Package Manager — `runtime.pkg`

> Replaces: `pip install` in Dockerfiles, `npm install` at app bootstrap, brew/apt-get in setup scripts, manual dependency management per environment.

The package manager primitive declares **what runtime dependencies an agent needs**, and the runtime satisfies them. `rt.pkg.ensure_python(["numpy>=2.0"])` installs numpy if not already available. The runtime caches, resolves conflicts, and handles cross-language dependency graphs.

**Providers:** pip (Python), npm (Node.js), uv (fast Python), conda (data science), brew (macOS), apt (Debian), Nix (declarative), MicroVM snapshot (pre-baked deps).

### ⑤ Storage — `runtime.storage`

> Replaces: `fs.writeFile` with hard-coded paths, SQLite file paths in code, S3 bucket ARNs, Postgres connection strings.

The storage primitive provides **a uniform key-value or document-store interface** for persistent state. The app writes key-value pairs; the runtime routes them to the configured backend. No path strings, no connection strings, no SQL dialects — just `rt.storage.put(namespace, key, value)` and `rt.storage.get(namespace, key)`.

**Providers:** SQLite (local), Postgres (shared), S3/MinIO (cloud), Redis (ephemeral), JSONL file (OpenClaw session format), in-memory Map (testing).

### ⑥ Secrets — `runtime.secrets`

> Replaces: `.env` files, `os.environ["OPENAI_API_KEY"]`, `process.env.GITHUB_TOKEN`, secrets committed to git, SSH keys in agent context.

The secrets primitive provides **named, audited access to credentials**. The app calls `rt.secrets.get("openai-api-key")`. The runtime resolves the secret from the configured backend. Every access is logged. Secrets are never exposed to the prompt context or to tool execution.

**Providers:** macOS Keychain (local), HashiCorp Vault (enterprise), 1Password CLI, `.env` file (development, not committed), AWS Secrets Manager, GCP Secret Manager, Kubernetes Secrets.

### ⑦ Observability — `runtime.observability`

> Replaces: `console.log` with environment-dependent sinks, hard-coded Langfuse endpoints, OTel configuration per deployment.

The observability primitive provides **structured, routable telemetry**. The app emits traces, logs, and metrics through the runtime. The runtime routes them to the configured sink. The app never knows whether telemetry goes to Langfuse, file, stdout, or an OTel collector.

**Providers:** Langfuse, OpenLLMetry/Otel, stdout (dev), file (server), Prometheus (metrics), Phoenix (traces), custom webhook.

> **What about filesystem and process?** The Missing Kernel's filesystem (AgentFS) and process primitives are absent here intentionally. Filesystem access through a tool bound to the host path is a *kernel-level concern* — the kernel provides VFS, namespaces, overlayfs, and all the isolation an agent needs. The userland runtime doesn't need to re-abstract files. It needs to abstract **everything that's not files** — the environment-shaped concerns the kernel doesn't know about. That's the gap.

### How these primitives draw on OpenAI's SDK pieces

OpenAI's Agents SDK ships pieces that we consume per-primitive — not as a single wrapped backend. The runtime is free to use OpenAI's piece, a non-OpenAI piece, or our own implementation for any given primitive:

| Runtime primitive | OpenAI SDK piece used | Other viable implementations |
|---|---|---|
| `runtime.pkg` | `Manifest` (files, dirs, git repos, mounts, env, users) | Nix flakes, Docker layers, local file tree, conda env spec |
| `runtime.storage` | Workspace files + storage mounts (S3/GCS/R2/Box/Azure) | SQLite, Postgres, JSONL file, in-memory |
| `runtime.secrets` | `Manifest.environment` (ephemeral flag) + mount credentials | macOS Keychain, Vault, `.env` file, K8s Secrets |
| `runtime.ipc` | Handoffs (agent-to-agent) + port exposure | Unix socket, NATS, Redis Pub/Sub, SQS, in-process queue |
| `runtime.observability` | Agents SDK tracing | OpenTelemetry, Langfuse, stdout/file, Phoenix |
| `runtime.identity` | Per-agent cryptographic identity (if embedded agent uses it) | OIDC, macOS Keychain, Agent Auth Protocol, dev `.env` |
| `runtime.tokens` | *No SDK piece* (OpenAI bills via API pricing, not runtime enforcement) | Runtime-native: JSON budget, DynamoDB, OTel-derived spend |

**Six primitives** can draw on a piece of the OpenAI SDK. **One** (`tokens`) has no SDK piece at all — it's genuinely runtime-native. The runtime does *not* wrap the SDK as a provider; it consumes its pieces *individually* alongside non-OpenAI pieces, and the `runtime.json` decides which piece to use per deployment.

---

## The interface

Concrete code. What the application sees. Simple enough that no one needs a framework guide.

### Startup: load the runtime config

```python
from pyxen import Runtime

rt = await Runtime.load("runtime.json")
# rt is now configured with the right implementations for this environment
```

### Identity: who's calling?

```python
me = await rt.identity.current()
# Identity(id="jason@...", source="keychain", name="Jason Cui")

github = await rt.identity.for_target("github.com")
# Credential(token="ghp_...", expires_at=...)

openai = await rt.identity.for_target("api.openai.com")
# Credential(api_key="sk-proj-...", org_id="org-...")
```

### Token budget: can I spend?

```python
check = await rt.tokens.check("gpt-4o", 5000)
# CheckResult(allowed=True, remaining=15000, budget=Budget(daily=50000, spent=35000))

# After the call finishes, charge it:
await rt.tokens.charge("gpt-4o", tokens=actual_tokens, dollars=actual_cost)

# If budget is exceeded:
fail = await rt.tokens.check("claude-opus", 10000)
# CheckResult(allowed=False, remaining=0, reason="Daily budget exhausted")
```

### IPC: talk to another process or agent

```python
# Send a request and wait for reply
reply = await rt.ipc.send("research-agent", {"type": "research", "query": "..."})

# Subscribe to a stream
async for msg in rt.ipc.subscribe("price-alerts"):
    print("Price alert:", msg.data)
```

### Package manager: ensure dependencies

```python
# Ensure python deps
await rt.pkg.ensure_python(["numpy>=2.0", "pandas>=2.2", "httpx"])

# Or load from a pyproject.toml
await rt.pkg.ensure_from_manifest("pyproject.toml")
```

### Storage: persist state

```python
await rt.storage.put("sessions", "session-abc", {"status": "completed", "result": "..."})
session = await rt.storage.get("sessions", "session-abc")
# {"status": "completed", "result": "..."}

# Query (provider-dependent)
recent = await rt.storage.query("sessions", filter={"status": "completed"}, limit=10)
```

### Secrets: get credentials

```python
api_key = await rt.secrets.get("openai-api-key")
# Returns "sk-proj-..."
# Every access is logged. Never exposed to a model context window.
```

### Observability: emit telemetry

```python
async with rt.observability.trace("agent-run") as span:
    span.set_attribute("model", "gpt-4o")
    span.log("info", "Starting research workflow")
    result = await do_research()
    span.set_attribute("result_length", len(result))
    return result
```

---

## The provider model

`runtime.json` is the single environment-definition artifact. It maps each primitive to an implementation with its own configuration. The app never touches it at import time — `Runtime.load()` reads it at startup and wires everything up.

```json
{
  "version": "1",
  "identity": {
    "implementation": "keychain",
    "config": { "service": "runtime-default" }
  },
  "tokens": {
    "implementation": "json_budget",
    "config": {
      "path": "./budget.json",
      "defaults": {
        "daily": 50000,
        "models": {
          "gpt-4o": { "cost_per_1k": 0.01, "input_cost_per_1k": 0.0025 }
        }
      }
    }
  },
  "ipc": {
    "implementation": "unix_socket",
    "config": { "path": "/tmp/runtime-ipc" }
  },
  "pkg": {
    "implementation": "pip",
    "config": { "cache_dir": "~/.cache/runtime-deps", "python": "python3.12" }
  },
  "storage": {
    "implementation": "sqlite",
    "config": { "path": "./runtime-data.db" }
  },
  "secrets": {
    "implementation": "keychain",
    "config": { "service": "runtime-secrets" }
  },
  "observability": {
    "implementation": "stdout",
    "config": { "level": "debug", "format": "json" }
  }
}
```

### Same app, two configs

| Local (Python dev workstation) | Cloud (shared OpenClaw / sandbox) |
|---|---|
| `runtime.json` uses: keychain + JSON budget + unix-socket + pip + SQLite + stdout. Zero external dependencies, starts in 50ms, runs fully offline. The same app executes identically to cloud — just slower and with local state. *Note: the app is a plain Python CLI or web app. No agents required.* | `runtime.json` uses: OIDC + DynamoDB budget + NATS + pre-baked deps + Postgres + Vault + OTel collector. Full isolation, shared state, cost enforcement, audit trail. The same app, no code changes. *Same plain Python app; agents are an optional add-on if the app later needs them.* |

### Same app, OpenAI's SDK pieces consumed per-primitive

The same runtime can draw on individual pieces of the OpenAI Agents SDK for each primitive. The runtime doesn't import *the SDK* — it imports the pieces it needs (e.g., `from openai.agents import Manifest, SandboxClient, handoffs`) and uses them where they fit. The app's source code never imports the OpenAI SDK at all.

```json
{
  "version": "1",
  "pkg": {
    "implementation": "openai_manifest",
    "config": {
      "manifest": {
        "entries": {
          "AGENTS.md": { "file": { "content": "..." } },
          "task.md":   { "file": { "content": "..." } }
        }
      }
    }
  },
  "storage":  { "implementation": "openai_mount_s3",  "config": { "bucket": "..." } },
  "secrets":  { "implementation": "openai_env_injection", "config": { "ephemeral": true } },
  "ipc":      { "implementation": "openai_handoffs",  "config": {} },
  "observability": { "implementation": "openai_tracing", "config": {} },
  "tokens":   { "implementation": "runtime_native_budget", "config": { "path": "..." } },
  "identity": { "implementation": "oidc", "config": { "issuer": "..." } }
}
```

The app's source code is identical to the local config above. The only thing that changed is *which pieces* the runtime uses for each primitive. The OpenAI SDK is not wrapped as a backend; its libraries are consumed as sources of implementations. The runtime could swap any of them out for a non-OpenAI piece (Anthropic tracing, Vault for secrets, NATS for IPC) without changing app code.

### Real-world scenario: shipping someone else's app

> Someone writes a Python app, bundles it with a `runtime.json` and a `runtime.local.json`. You install it with `pip install <their-app>` and copy their `runtime.local.json` as your `runtime.json`. The app works on your machine. To deploy to your cluster, the deploy tool generates your `runtime.cloud.json`. Same app, your environment.

---

## Prior art & recent research

This isn't a new idea. The industry is converging on the same pattern from multiple directions. Here's what's already out there.

### Direct parallels

**WASI (WebAssembly System Interface).** A standardized system interface for WebAssembly modules. The host provides APIs for filesystem, clocks, random, sockets. The module imports `wasi_snapshot_preview1`. The host implements it. **Same WASM + different WASI host = different environment.** The closest existing realization of the userland runtime pattern. WASI proves that a portable runtime interface can abstract OS differences. The Portable Userland applies the same pattern to *application-level* environment concerns that WASI doesn't cover.

**OpenAI Agents SDK · Apr 2026 — Manifest Abstraction & SDK Pieces.** OpenAI's April 2026 Agents SDK update introduces a "Manifest abstraction" that *"describe[s] an agent's workspace to make environments portable across different providers."* Supported sandbox providers: Blaxel, Cloudflare, Daytona, E2B, Modal, Runloop, Vercel. The SDK also ships `handoffs` for inter-agent IPC, `tracing` for observability, and `apply_patch` / `shell` tools. **The best existing source of *pieces* for the runtime's primitives.** Use the SDK's pieces where they fit. Don't replace them. Don't treat them as a single backend.

**OpenHands SDK · arXiv 2511.03690v2 — Workspace Abstraction.** OpenHands provides a "workspace abstraction" that "enables agents to run locally or in secure, containerized environments with minimal code changes." The SDK separates the agent's harvest (logic) from its compute environment. Confirms the *harvest/environment separation* pattern. The workspace abstraction is one primitive in the userland runtime model.

**Agent Auth Protocol · 2026.** A protocol assigning "each runtime agent its own cryptographic identity with scoped capabilities and an independent lifecycle." Moves beyond OAuth's "one identity per application" by enabling per-agent, user-isolated credentials. Proves the identity primitive is real and urgent.

**Microsoft Agent Framework · Apr 2026 — Kernel-Decoupled Tools.** Microsoft's Agent Framework 1.0 (successor to Semantic Kernel) explicitly decouples tools from the kernel. The `[KernelFunction]` methods are "highly portable assets across Microsoft's AI stack" — tools don't need to flow through a kernel at all. Direct evidence that even the "kernel-shaped" thinking in the industry is moving toward userland tools.

**Dagger Functions · 2025–2026.** Containerized SDK with provider swapping. Dagger provides a Sandbox runtime for AI coding agents: Dagger Functions run in containerized, isolated environments. LLMs can call Dagger Functions "as programmable primitives" integrated into any OCI-compatible environment. Confirms the "run anywhere" provider model.

**Nix Ecosystem.** Nix provides a purely functional package manager and declarative language for "Development Environments as Code" (DEaC). A `shell.nix` or `flake.nix` describes the full environment: tools, libraries, services, configs. The original "environment as code" pattern. Nix captures *system-level* environment; the Portable Userland captures *application-level* environment.

### Research papers

| Paper / Talk | Year | Key idea | Relevance |
|---|---|---|---|
| **PARAVIRT: Userland Containers for Mobile** | Nov 2025 | Userland containerization on Linux/Android via modified kernel + paravirtualized syscall interface for I/O | Proves userland-level abstraction without kernel patches |
| **Remote Direct Code Execution (RDX)** | Nov 2025 | "CodeFlow abstraction" to inject runtime extensions (WASM, BPF, UDF) across RDMA networks | The CodeFlow abstraction is a portable IPC primitive |
| **Object-as-a-Service (OaaS) / Oparaca** | Dec 2025 | Unified resource, state, and workflow management into a single object-oriented abstraction for edge-cloud-native apps | The OaaS abstraction captures environment behind a uniform interface |
| **AgenticOS @ SOSP 2026** | Jun 2026 | Academic agenda for OS abstractions tailored for agents: dynamic sandboxing, eBPF observability, agent IPC | The academic community recognizing the gap |
| **Memory Worth (MW) Primitive** · arXiv 2604.12007 | Apr 2026 | Two-counter per-memory signal: success correlation vs decay. Active forgetting as a first-class primitive. | Could be a runtime observability callback |
| **OpenHands Software Agent SDK** · arXiv 2511.03690 | Rev. Apr 2026 | Composable agent SDK with workspace abstraction for local ↔ containerized code changes. REST/WebSocket IPC. | The most complete published SDK implementation of the userland runtime pattern |
| **Agent Continuity Engine** · wonderingmax, 2026 | 2026 | Behavioral Distillation Layer to observe, package, and rehydrate agent behavior across different model environments | Tackles behavioral portability — complement to the runtime's environmental portability |

### The pattern across all prior art

The industry and academia are converging on the same conclusion from different angles:

- **WASI** says: abstract the OS behind a portable interface
- **OpenAI Manifest** says: abstract the sandbox behind a manifest
- **OpenHands SDK** says: abstract the workspace behind an SDK
- **Agent Auth Protocol** says: abstract identity behind a cryptographic protocol
- **Microsoft Framework 1.0** says: decouple tools from kernel
- **Nix** says: declare environments in code
- **OaaS / Oparaca** says: abstract edge-cloud environment behind objects

> **What's missing:** Each of these captures *one* primitive. WASI doesn't know about app identity. OpenAI Manifest doesn't know about token budgets. Agent Auth Protocol doesn't know about packages. **The Portable Userland unifies all seven primitives behind a single runtime interface with a single config file.** The industry is building all the pieces; the missing layer is the runtime that *composes* them — and the right first step is to **consume the pieces that already exist individually** (OpenAI's SDK libraries for some primitives, WASI for cross-platform hosting, Vault for secrets, etc.) rather than reimplement them.

---

## The portability guarantee

How the userland runtime makes the "same app, different machine" claim concrete.

### The problem it solves

Today, taking an OpenClaw workflow from Jason's laptop to a shared cloud requires:

- Replacing `$GITHUB_TOKEN` env var loading → OIDC token exchange
- Replacing SQLite file paths → Postgres connection strings
- Replacing macOS keychain → Vault secrets
- Replacing `pip install` → pre-baked container image
- Replacing `/tmp/runtime-ipc/` → NATS cluster address
- Replacing JSON budget file → DynamoDB budget table
- Replacing `console.log` → OTel collector endpoint

That's **7 changes** to the app code. The port is a partial rewrite.

### With the userland runtime

The same migration is one file change:

```bash
# Local machine:
$ cp runtime.local.json runtime.json
$ python my_app.py
# App connects through local providers. Works in 50ms.
```

```bash
# Cloud deploy:
$ cp runtime.cloud.json runtime.json
$ python my_app.py
# Same app. Same binary. Different providers. Works identically.
```

**The portability guarantee:** as long as the provider implementations are semantically compatible (they all implement the same interface), the application code never changes. The `runtime.json` file is the **only** deployment-specific artifact.

### What this enables

1. **Write once, run anywhere.** A developer builds and tests an agent on their laptop with local providers. The same agent deploys to a team-shared OpenClaw, to a cloud CI/CD pipeline, and to a client's private instance. One codebase, three runtimes.

2. **Test locally, audit in cloud.** Local identity is unauthenticated (dev mode). Cloud identity is OIDC + ABAC. Local storage is SQLite. Cloud storage is Postgres with immutable audit log. The app logic is identical; the guarantees differ by environment.

3. **Third-party package as environment.** Someone writes an agent app, bundles it with a `runtime.json` and a `runtime.local.json`. You install it with `npx <their-app> deploy --env cloud`. The deploy tool generates your `runtime.cloud.json` for your cluster. Same app, your environment.

4. **Provider swap = capability upgrade.** An app built on the runtime automatically gets new capabilities when a provider is swapped: switch `secrets` from `.env` to `Vault` and suddenly every secrets access is audited. No code change. The provider upgrade is invisible to the app.

> **The ultimate test:** A coworker should be able to take your runtime-based agent app, run `cp runtime.local.json runtime.json && python my_app.py` on their machine, and have it work — even if they use macOS, the agent connects to different services, and their secrets live in a different keychain entry. The app works because the runtime abstracts the environment, and the `runtime.json` configures the right local providers.

---

## Honest critique

What this thesis gets wrong, where the hard parts are, and why you might still want kernel primitives.

### Strengths

- **Immediately consumable.** `pip install` is O(seconds). Kernel patches are O(years).
- **Platform-agnostic.** Works on Linux, macOS, Windows, mobile, cloud — any runtime that supports Python.
- **Provider-swappable.** The config-driven provider model is the only way to make portability real.
- **Evolvable.** Add a primitive, add providers, bump the minor version. No kernel compatibility concerns.
- **Composable with kernel primitives.** When the kernel gets real `agent_fork(2)`, the runtime's `pkg` provider just installs into the CoW namespace. The runtime enables portability; kernel primitives enable enforcement.

### Weaknesses

- **No hard enforcement.** A userland runtime can't enforce token budgets the way a kernel cgroup can. A rogue app can bypass the runtime by calling the provider directly.
- **Startup overhead.** Resolving providers in `runtime.json` takes milliseconds, not nanoseconds. For short-lived agents (<1s), this matters.
- **Semantic mismatch risk.** Two providers for the same primitive may have subtly different semantics (e.g., "query" is SQL-aware in Postgres but key-only in SQLite). The runtime can only abstract so much.
- **Versioning surface.** Seven primitives, each with 2-5 providers, all versioned independently — the compatibility matrix grows fast.
- **It's another dependency.** Adding a runtime to every agent project is friction a kernel primitive doesn't have.

### If kernel primitives existed, this runtime is still necessary

Even if Linux tomorrow ships all 8 Missing Kernel syscalls, you still need a userland runtime. The kernel provides `agent_fork(2)` (process isolation), `cgroup_agent` (resource enforcement). It doesn't provide `runtime.identity.for("github.com")` or `runtime.secrets.get("openai-key")`. These are inherently application-level concerns. Kernel primitives and userland runtime are **complementary**, not competing.

The real question is: **which layer should you ship first?** The Missing Kernel says ship kernel primitives. The Portable Userland says ship the userland runtime — because it's immediately usable by any app developer today, and it makes the kernel debate matter less. When the kernel catches up, the runtime can use it as a provider.

> **The honest tradeoff:** Shipping the userland runtime first means starting with **convention over enforcement**. An app that bypasses the runtime can't be stopped. But an app that follows the pattern is instantly portable. **Convention reaches more users than enforcement.** The Missing Kernel's question is "how do we enforce isolation?" The Portable Userland's question is "how do we make apps portable?" Both matter. The right first step depends on which problem your users are actually hitting today. In 2026, the answer is portability.

---

## The bet

If I had to put one bet on the 2026-2028 agent stack, this is it.

By 2027, every serious agent runtime will have a "runtime interface" — a way to inject environment-specific providers without changing application code. The shape of that interface will look like the 7 primitives: identity, tokens, IPC, packages, storage, secrets, observability. WASI will have inspired a higher-level application runtime standard. OpenAI's Manifest will have grown beyond sandbox portability to full environment portability. OpenHands' workspace abstraction will be the default for cloud agents.

The Missing Kernel's 8 primitives will eventually be real syscalls on Linux and Windows. But they will ship **after** the userland runtime — because the runtime is faster to build, easier to adopt, and solves the immediate problem (portability) that enterprises and solo devs alike are hitting today.

The team that builds the userland runtime — a single `pip install`-able package with 7 clean primitives, a provider registry, and a `runtime.json` config format — will have the dominant abstraction for portable agent applications by 2027. The kernel debate will be a footnote. The runtime will be the reality.

> **A working hypothesis:** Build the userland runtime as a **Python package** (`pyxen`) on PyPI. Organize it per-primitive, not per-vendor: `impl/storage/`, `impl/identity/`, `impl/ipc/`, `impl/pkg/`, `impl/secrets/`, `impl/observability/`, `impl/tokens/`. Each impl sub-package hosts multiple implementations; any implementation can *reach into* OpenAI SDK pieces (or Nix, Vault, NATS, whatever) as needed. **No top-level `impl/openai`** — the OpenAI SDK is a source of pieces, not a wrapped backend. Ship agent-less demos: a minimal CLI, a small FastAPI app, a data-pipeline script. **Ship the interface, the local impls, and the per-primitive OpenAI piece integrations. Nothing more.**

### The two bets side by side

**The Missing Kernel Bet:** *"Port **BranchFS to a Linux kernel module** with proper `agent_fork(2)` semantics. That's the single primitive the stack needs most."*

**The Portable Userland Bet:** *"Ship **pyxen** as a Python package on PyPI. The 7 primitives are what apps actually need to be portable. When the kernel gets `agent_fork(2)`, the runtime's `pkg` implementation uses it. But until then, the runtime works without it."*

---

*This document is a research note accompanying the pyxen codebase. It is intentionally a complement, not a rebuttal, of "The Missing Kernel — Agent OS Primitives in 2026." The Missing Kernel is right about what needs to exist. It is wrong about where those things should live. The userland runtime is the layer that makes agent apps portable today. The kernel primitives are the layer that enforces guarantees tomorrow. Build both. Ship the runtime first.*

*v0.2 revision (June 14, 2026): clarified that the runtime is **general-purpose** (apps with or without agents), that it is implemented in **Python**, and that **OpenAI's SDK libraries are consumed per-primitive rather than wrapped as a single provider**. MVP demos are agent-less Python apps (CLI / web / pipeline). The agent connection is a future benefit, not a v0 requirement.*

*v0.3 revision (June 14, 2026): package structure is **per-primitive** — not a top-level `impl/openai` vs `impl/local` split. Each primitive's impls can reach into OpenAI SDK pieces (or any other source) as needed. Working name: `pyxen`. Repo: private, personal org, GitHub Actions CI.*
