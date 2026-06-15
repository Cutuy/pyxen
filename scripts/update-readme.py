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

def discover_primitives() -> dict[str, dict[str, str]]:
    """Scan core/ for Protocol classes and return {name: {label, question}}."""
    result: dict[str, dict[str, str]] = {}
    for pyfile in sorted(CORE_DIR.glob("*.py")):
        if pyfile.name in ("__init__.py", "manifest.py", "errors.py", "runtime.py"):
            continue
        name = pyfile.stem  # e.g. "identity", "storage"
        # Use the file-level docstring first line as the description
        question = ""
        try:
            tree = ast.parse(pyfile.read_text(encoding="utf-8"))
            doc = ast.get_docstring(tree)
            if doc:
                question = doc.split("\n")[0].strip()
        except Exception:
            pass
        result[name] = {"label": name, "question": question}
    return result


# ── 2. Discover implementations from impl/ ───────────────────────────

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
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
        if doc:
            return doc.split("\n")[0].strip()
    except Exception:
        pass
    return ""


# ── 3. Build the markdown table ──────────────────────────────────────

def build_table(
    primitives: dict[str, dict[str, str]],
    impls: dict[str, list[dict[str, str]]],
) -> str:
    """Generate the primitives table with implementation lists."""
    lines: list[str] = []
    lines.append("| Primitive | What it answers | Implementations |")
    lines.append("|---|---|---|")
    for prim, info in primitives.items():
        label = info["label"]
        question = info["question"]
        impl_list = impls.get(prim, [])
        if impl_list:
            items = []
            for i in impl_list:
                entry = f"`{i['name']}`"
                if i['doc']:
                    entry += f" — {i['doc']}"
                items.append(f"- {entry}")
            impl_col = "<br>" + "<br>".join(items)
        else:
            impl_col = "—"
        lines.append(f"| `{label}` | {question} | {impl_col} |")
    return "\n".join(lines)


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


def patch_readme(
    readme: str,
    primitives: dict[str, dict[str, str]],
    impls: dict[str, list[dict[str, str]]],
    new_roadmap: str | None,
) -> str:
    """Replace the table and roadmap sections."""
    result = readme
    new_table = build_table(primitives, impls)

    # Replace table
    result = _replace_section(result, "## What", new_table)

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

    patched = patch_readme(current, primitives, impls, new_roadmap)

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
