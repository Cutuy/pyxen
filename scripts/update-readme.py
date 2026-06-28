#!/usr/bin/env python3
"""Auto-maintain README: discover primitives + impls, update table, optionally LLM-refresh roadmap.

Called from the pre-push hook.

The mechanical parts (primitive discovery, impl table generation) run unconditionally.
The LLM part (roadmap / TODO updates) fires only if a usable API key is available.

API key resolution order:
  1. DEEPSEEK_API_KEY env var
  2. .env file in repo root (DEEPSEEK_API_KEY=xxx)
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
CORE_DIR = REPO_ROOT / "src" / "pyxen" / "core"
IMPL_DIR = REPO_ROOT / "src" / "pyxen" / "impl"
EXAMPLES_DIR = REPO_ROOT / "examples"
ENV_PATH = REPO_ROOT / ".env"


# ── 0. API key resolution ───────────────────────────────────────────

def _resolve_api_key() -> str | None:
    """Check DEEPSEEK_API_KEY from env, then .env file."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    if ENV_PATH.exists():
        try:
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            pass
    return None


# ── 1. Discover primitives from core/ Protocols ─────────────────────

PRIMITIVE_QUESTIONS: dict[str, str] = {
    "identity": "Who's calling?",
    "tokens": "Within LLM budget?",
    "ipc": "Message another process",
    "pkg": "Dependencies present?",
    "storage": "Persist a record",
    "secrets": "Get a credential",
    "observability": "Emit a trace / log",
}


# ── 1b. Extension metadata ───────────────────────────────────────────

EXTENSION_QUESTIONS: dict[str, str] = {
    "cron": "Schedule recurring tasks",
}


def discover_primitives() -> dict[str, dict[str, str]]:
    """Scan core/ for Protocol classes and return {name: {label, question}}."""
    result: dict[str, dict[str, str]] = {}
    for pyfile in sorted(CORE_DIR.glob("*.py")):
        if pyfile.name in ("__init__.py", "manifest.py", "errors.py", "runtime.py"):
            continue
        name = pyfile.stem
        result[name] = {"label": name, "question": PRIMITIVE_QUESTIONS.get(name, "")}
    return result


# ── 2. Discover implementations from impl/ ───────────────────────────

# ── 1c. Discover extensions from core/ext/ ──────────────────────────

def _discover_extension_backends(ext_dir: Path) -> list[dict[str, str]]:
    """Scan an extension dir for backends (``_<name>.py``) and ``state.py``."""
    backends: list[dict[str, str]] = []
    for pyfile in sorted(ext_dir.glob("*.py")):
        name = pyfile.name
        # Include only: _<name>.py backends and state.py
        # __init__.py starts with _ but is not a backend
        if name == "__init__.py":
            continue
        if not (name.startswith("_") and name.endswith(".py")) and name != "state.py":
            continue
        display_name = name.removeprefix("_").removesuffix(".py")
        doc = _first_doc_line(pyfile)
        if not doc:
            if name == "state.py":
                doc = "execution history (timestamps, exit codes) queryable via runtime extension API."
            elif name.startswith("_"):
                doc = f"{display_name} backend."
        backends.append({"name": display_name, "doc": doc})
    return backends


def discover_extensions() -> list[dict[str, Any]]:
    """Scan ``core/ext/`` directories; return ``[{name, question, backends}]``."""
    ext_dir = CORE_DIR / "ext"
    if not ext_dir.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for entry in sorted(ext_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        init_py = entry / "__init__.py"
        if not init_py.exists():
            continue

        name = entry.name
        question = EXTENSION_QUESTIONS.get(name, "")
        if not question:
            # Fallback: read first line of module docstring
            try:
                tree = ast.parse(init_py.read_text(encoding="utf-8"))
                doc = ast.get_docstring(tree)
                if doc:
                    question = doc.split(".")[0].strip()
            except Exception:
                pass

        backends = _discover_extension_backends(entry)

        result.append({
            "name": name,
            "question": question,
            "backends": backends,
        })
    return result


def discover_impls() -> dict[str, list[dict[str, str]]]:
    """Scan impl/ directories and return {primitive: [{name, doc}]."""
    result: dict[str, list[dict[str, str]]] = {}
    for prim_dir in sorted(IMPL_DIR.iterdir()):
        if not prim_dir.is_dir() or prim_dir.name.startswith("_"):
            continue
        impls: list[dict[str, str]] = []
        for pyfile in sorted(prim_dir.glob("*.py")):
            if pyfile.name == "__init__.py":
                continue
            name = pyfile.stem
            doc = _first_doc_line(pyfile)
            impls.append({"name": name, "doc": doc})
        if impls:
            result[prim_dir.name] = impls
    return result


def _first_doc_line(path: Path) -> str:
    """Return first docstring line, stripped of the leading ``name`` prefix."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
        if doc:
            line = doc.split("\n")[0].strip()
            # Strip leading ``name`` type — prefix since name is already shown
            if line.startswith("``"):
                line = line.split(" — ", 1)[-1] if " — " in line else line.split("``", 2)[-1].lstrip()
            return line
    except Exception:
        pass
    return ""


# ── 2b. Discover examples from examples/ ────────────────────────────

_RUN_BLOCK_RE = re.compile(
    r"Run with[^\n]*?::?\s*\n((?:[ \t]+.+\n?)+)",
    re.MULTILINE,
)


def discover_examples() -> list[dict[str, str]]:
    """Scan ``examples/*/`` and return one entry per example directory.

    Each entry: ``{name, blurb, run_cmd, rel_path}``. The primary file is
    the alphabetically-first ``.py`` file in the folder (ignoring
    ``__init__.py``); its module docstring drives the blurb + run command.
    """
    result: list[dict[str, str]] = []
    if not EXAMPLES_DIR.is_dir():
        return result
    for ex_dir in sorted(EXAMPLES_DIR.iterdir()):
        if not ex_dir.is_dir() or ex_dir.name.startswith(("_", ".")):
            continue
        py_files = sorted(
            p for p in ex_dir.glob("*.py") if p.name != "__init__.py"
        )
        if not py_files:
            continue
        primary = py_files[0]
        try:
            doc = ast.get_docstring(ast.parse(primary.read_text(encoding="utf-8"))) or ""
        except (OSError, SyntaxError):
            doc = ""
        result.append({
            "name": ex_dir.name,
            "blurb": _blurb_after_title(doc),
            "run_cmd": _extract_run_block(doc),
            "rel_path": f"examples/{ex_dir.name}",
        })
    return result


def _blurb_after_title(doc: str) -> str:
    """Return the paragraph after the title (``name — short description``).

    If the docstring has only one paragraph (title and blurb fused on the
    first line), that paragraph is returned as the blurb.
    """
    paragraphs = [p.strip() for p in doc.split("\n\n") if p.strip()]
    if len(paragraphs) >= 2:
        return paragraphs[1]
    if paragraphs:
        return paragraphs[0]
    return ""


def _extract_run_block(doc: str) -> str:
    """Pull the first code block under ``Run with`` / ``Run with::``.

    Handles both reST (``::``) and markdown (``:``) conventions. The
    common leading indent is stripped so the block can be dropped into a
    fenced code block.
    """
    m = _RUN_BLOCK_RE.search(doc)
    if not m:
        return ""
    lines = m.group(1).rstrip("\n").split("\n")
    indents = [len(l) - len(l.lstrip(" \t")) for l in lines if l.strip()]
    if not indents:
        return ""
    min_indent = min(indents)
    return "\n".join(l[min_indent:] for l in lines).rstrip()


# ── 3a. Build the primitive-impl table ──────────────────────────────

def build_table(
    primitives: dict[str, dict[str, str]],
    impls: dict[str, list[dict[str, str]]],
) -> str:
    lines: list[str] = []
    lines.append("| Primitive | What it answers | Backends |")
    lines.append("|---|---|---|")
    for prim, info in primitives.items():
        label = info["label"]
        question = info["question"]
        impl_list = impls.get(prim, [])
        if impl_list:
            names = ", ".join(f"`{i['name']}`" for i in impl_list)
            impl_col = f"{names}"
        else:
            impl_col = "—"
        lines.append(f"| `{label}` | {question} | {impl_col} |")
    return "\n".join(lines)


# ── 3b. Build the extensions table ───────────────────────────────────

def build_extensions_table(extensions: list[dict[str, Any]]) -> str:
    if not extensions:
        return "_(no extensions yet)_\n"
    lines: list[str] = []
    lines.append("| Extension | What it adds | Backends |")
    lines.append("|---|---|---|")
    for ext in extensions:
        label = ext["name"]
        question = ext["question"]
        backends = ext["backends"]
        if backends:
            names = ", ".join(f"`{bk['name']}`" for bk in backends)
            impl_col = f"{names}"
        else:
            impl_col = "—"
        lines.append(f"| `{label}` | {question} | {impl_col} |")
    return "\n".join(lines) + "\n"


# ── 4. LLM roadmap update (DeepSeek, OpenAI-compatible) ──────────────

DEEPSEEK_BASE = "https://api.deepseek.com"


def llm_roadmap_updates(
    current_readme: str,
    primitives: dict[str, dict[str, str]],
    impls: dict[str, list[dict[str, str]]],
) -> str | None:
    """Ask DeepSeek to suggest roadmap changes. Returns new Roadmap section text or None."""
    api_key = _resolve_api_key()
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE)

        prim_summary = "\n".join(
            f"  - {prim}: {info['question']}"
            for prim, info in sorted(primitives.items())
        )
        impl_summary = "\n".join(
            f"  - {prim}: {', '.join(i['name'] for i in impl_list)}"
            for prim, impl_list in sorted(impls.items())
        )

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical maintainer. Given the current README, the list "
                        "of primitives, and available implementations, suggest an updated "
                        "Roadmap section. "
                        "Drop any line that describes something already implemented. "
                        "Keep only future TODOs and high-level roadmap items. "
                        "Keep it concise — bullet list format. "
                        "Output ONLY the new Roadmap section content, nothing else. "
                        "Each line should start with `- `."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CURRENT README ROADMAP SECTION:\n"
                        f"{_extract_section(current_readme, '## Roadmap')}\n\n"
                        f"PRIMITIVES ({len(primitives)} total):\n{prim_summary}\n\n"
                        f"IMPLEMENTATIONS AVAILABLE:\n{impl_summary}\n\n"
                        f"Generate an updated Roadmap section based on what's completed."
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=300,
        )
        content = resp.choices[0].message.content
        if content:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("\n```", 1)[0]
            return content.strip()
    except Exception as e:
        print(f"  LLM call failed: {e}")
    return None


def _extract_section(md: str, heading: str) -> str:
    lines = md.split("\n")
    start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i
            break
    if start == -1:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


# ── 5. Patch README ──────────────────────────────────────────────────

TABLE_ANCHOR = "<!-- impl-table -->"
ROADMAP_ANCHOR = "<!-- roadmap -->"


def _parse_existing_examples(readme: str) -> dict[str, str]:
    """Extract {name: blurb} from the existing examples table, if any."""
    result: dict[str, str] = {}
    m = re.search(r"## Examples\s*\n+(.*?)(?=\n## )", readme, re.DOTALL)
    if not m:
        return result
    for line in m.group(1).split("\n"):
        # Match: | [`name`](./path/) | blurb |
        row = re.match(r"\|\s*\[`([^`]+)`\]\([^)]+\)\s*\|\s*(.+)\s*\|", line)
        if row:
            name = row.group(1).strip()
            blurb = row.group(2).strip()
            if name and name != "Example":
                result[name] = blurb
    return result


def _one_liner(text: str) -> str:
    """First sentence, ≤15 words, no markdown code spans, single-line."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"`[^`]+`", "", text)  # strip inline code
    m = re.match(r"([^.?!]+[.?!]?)", text.strip())
    if not m:
        return text.strip()[:80]
    s = m.group(1).strip()
    words = s.split()
    if len(words) > 15:
        s = " ".join(words[:15])
        if not s.endswith((".", "?", "!")):
            s += "…"
    return s


def build_examples_section(examples: list[dict[str, str]], existing_readme: str = "") -> str:
    if not examples:
        return ""
    # Preserve existing blurbs for examples already in the README
    existing = _parse_existing_examples(existing_readme)
    header = "| Example | What it shows |\n|---|---|"
    rows = [header]
    for ex in examples:
        blurb = existing.get(ex["name"]) or _one_liner(ex.get("blurb", ""))
        if not blurb:
            blurb = _one_liner(ex.get("name", "").replace("_", " "))
        rows.append(f"| [`{ex['name']}`](./{ex['rel_path']}/) | {blurb} |")
    return "\n".join(rows)


def patch_readme(
    readme: str,
    primitives: dict[str, dict[str, str]],
    impls: dict[str, list[dict[str, str]]],
    extensions: list[dict[str, Any]],
    new_roadmap: str | None,
    new_examples: str,
) -> str:
    """Replace the primitive table, extensions table, examples, and roadmap sections."""
    result = readme
    new_table = build_table(primitives, impls)
    new_ext_table = build_extensions_table(extensions)

    # Where extensions live: a short blurb after the table
    EXT_BLURB = (
        "Extensions live under `pyxen.core.ext.*` and are initialized from\n"
        "their section in `runtime.json`."
    )
    new_ext_section = new_ext_table + "\n" + EXT_BLURB + "\n"

    # Replace primitive table
    result = _replace_section(result, "## Primitives", new_table)

    # Replace extensions
    result = _replace_section(result, "## Extensions", new_ext_section)

    # Replace examples (only if auto-generated — currently a no-op stub)
    if new_examples:
        result = _replace_section(result, "## Examples", new_examples)

    # Replace roadmap
    if new_roadmap:
        result = _replace_section(result, "## Roadmap", new_roadmap)

    return result


def _replace_section(md: str, heading: str, new_content: str) -> str:
    lines = md.split("\n")
    start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i
            break
    if start == -1:
        return md
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break
    return "\n".join(lines[: start + 1]) + "\n\n" + new_content + "\n\n" + "\n".join(lines[end:]).lstrip("\n")


# ── 6. Main ──────────────────────────────────────────────────────────

def main() -> int:
    primitives = discover_primitives()
    impls = discover_impls()
    extensions = discover_extensions()
    examples = discover_examples()

    if not README_PATH.exists():
        print("README.md not found — skipping")
        return 0

    current = README_PATH.read_text(encoding="utf-8")

    new_roadmap = llm_roadmap_updates(current, primitives, impls)
    if new_roadmap:
        print(f"→ LLM generated roadmap update ({len(new_roadmap)} chars)")
    else:
        key_hint = "yes" if _resolve_api_key() else "no"
        print(f"→ LLM unavailable (api_key={key_hint}, openai package={_has_openai()}) — leaving roadmap as-is")

    new_examples = build_examples_section(examples, current)
    print(f"→ discovered {len(examples)} examples: {', '.join(e['name'] for e in examples) or '(none)'}")

    ext_names = [e["name"] for e in extensions]
    print(f"→ discovered {len(extensions)} extensions: {', '.join(ext_names) or '(none)'}")

    patched = patch_readme(current, primitives, impls, extensions, new_roadmap, new_examples)

    if patched != current:
        README_PATH.write_text(patched, encoding="utf-8")
        print(f"→ README updated — {len(patched)} chars")
    else:
        print("→ README unchanged")
    return 0


def _has_openai() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
