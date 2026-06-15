#!/usr/bin/env python3
"""Auto-maintain README: discover impls, update table, optionally ask LLM for roadmap.

Called from the pre-push hook. The mechanical parts (impl discovery, table generation)
run unconditionally. The LLM part (roadmap / TODO updates) fires only if
OPENAI_API_KEY is set and the openai package is installed.

Usage:
    PYTHONPATH=src python scripts/update-readme.py
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
IMPL_BASE = REPO_ROOT / "src" / "pyxen" / "impl"


# ── 1. Discover implementations ──────────────────────────────────────

PRIMITIVE_LABELS: dict[str, tuple[str, str]] = {
    "identity": ("identity", "Who's calling?"),
    "tokens": ("tokens", "Within LLM budget?"),
    "ipc": ("ipc", "Message another process"),
    "pkg": ("pkg", "Dependencies present?"),
    "storage": ("storage", "Persist a record"),
    "secrets": ("secrets", "Get a credential"),
    "observability": ("observability", "Emit a trace / log"),
}


def discover_impls() -> dict[str, list[dict[str, str]]]:
    """Scan impl/ directories and return {primitive: [{name, doc}]."""
    result: dict[str, list[dict[str, str]]] = {}
    for prim_dir in sorted(IMPL_BASE.iterdir()):
        if not prim_dir.is_dir() or prim_dir.name.startswith("_"):
            continue
        impls: list[dict[str, str]] = []
        for pyfile in sorted(prim_dir.glob("*.py")):
            if pyfile.name == "__init__.py":
                continue
            name = pyfile.stem
            # Extract first line of docstring
            doc = _first_doc_line(pyfile)
            impls.append({"name": name, "doc": doc})
        if impls:
            result[prim_dir.name] = impls
    return result


def _first_doc_line(path: Path) -> str:
    """Return the first line of the module docstring, or empty string."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
        if doc:
            return doc.split("\n")[0].strip()
    except Exception:
        pass
    return ""


# ── 2. Build the markdown table ──────────────────────────────────────

def build_table(impls: dict[str, list[dict[str, str]]]) -> str:
    """Generate the primitives table with implementation lists."""
    lines: list[str] = []
    lines.append("| Primitive | What it answers | Implementations |")
    lines.append("|---|---|---|")
    for prim in ["identity", "tokens", "ipc", "pkg", "storage", "secrets", "observability"]:
        label, question = PRIMITIVE_LABELS.get(prim, (prim, ""))
        impl_list = impls.get(prim, [])
        impl_col = ", ".join(
            f"`{i['name']}`" + (f" — {i['doc']}" if i['doc'] else "")
            for i in impl_list
        ) if impl_list else "—"
        lines.append(f"| `{label}` | {question} | {impl_col} |")
    return "\n".join(lines)


# ── 3. LLM roadmap update ───────────────────────────────────────────

def llm_roadmap_updates(current_readme: str, impls: dict[str, list[dict[str, str]]]) -> str | None:
    """Ask an LLM to suggest roadmap changes. Returns new Roadmap section text or None."""
    try:
        from openai import OpenAI
    except ImportError:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        client = OpenAI(api_key=api_key)

        impl_summary = "\n".join(
            f"  - {prim}: {', '.join(i['name'] for i in impl_list)}"
            for prim, impl_list in sorted(impls.items())
        )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical maintainer. Given the current README and a list "
                        "of available pyxen implementations, suggest an updated Roadmap section. "
                        "Mark completed items as done. Keep it concise — bullet list format. "
                        "Output ONLY the new Roadmap section content, nothing else. "
                        "Each line should start with `- `."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CURRENT README ROADMAP SECTION:\n"
                        f"{_extract_section(current_readme, '## Roadmap')}\n\n"
                        f"AVAILABLE IMPLEMENTATIONS:\n{impl_summary}\n\n"
                        f"Generate an updated Roadmap section."
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=300,
        )
        content = resp.choices[0].message.content
        if content:
            # Strip any markdown code fences the LLM might wrap in
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("\n```", 1)[0]
            return content.strip()
    except Exception:
        pass
    return None


def _extract_section(md: str, heading: str) -> str:
    """Extract text from a heading to the next heading (or EOF)."""
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


# ── 4. Patch README ──────────────────────────────────────────────────

TABLE_ANCHOR = "<!-- impl-table -->"
ROADMAP_ANCHOR = "<!-- roadmap -->"


def patch_readme(
    readme: str,
    new_table: str,
    new_roadmap: str | None,
) -> str:
    """Replace the table and roadmap sections."""
    result = readme

    # Replace table (anchored or between ## What and next heading)
    if TABLE_ANCHOR in result:
        result = _replace_between_anchors(result, TABLE_ANCHOR, "\n\n" + new_table + "\n\n")
    else:
        result = _replace_section(result, "## What", new_table)

    # Replace roadmap
    if new_roadmap:
        if ROADMAP_ANCHOR in result:
            result = _replace_between_anchors(result, ROADMAP_ANCHOR, "\n\n" + new_roadmap + "\n\n")
        else:
            result = _replace_section(result, "## Roadmap", new_roadmap)

    return result


def _replace_section(md: str, heading: str, new_content: str) -> str:
    """Replace everything between heading and next heading (or EOF)."""
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
    return "\n".join(lines[: start + 1]) + "\n\n" + new_content + "\n\n" + "\n".join(lines[end:])


def _replace_between_anchors(md: str, anchor: str, new_block: str) -> str:
    """Replace text between anchor and the next anchor or heading."""
    pattern = re.escape(anchor) + r".*?(\n## |\Z)"
    replacement = anchor + new_block + r"\1"
    return re.sub(pattern, replacement, md, count=1, flags=re.DOTALL)


# ── 5. Main ──────────────────────────────────────────────────────────

def main() -> int:
    impls = discover_impls()

    if not README_PATH.exists():
        print("README.md not found — skipping")
        return 0

    current = README_PATH.read_text(encoding="utf-8")
    table = build_table(impls)

    new_roadmap = llm_roadmap_updates(current, impls)
    if new_roadmap:
        print(f"→ LLM generated roadmap update ({len(new_roadmap)} chars)")
    else:
        print("→ LLM unavailable (no API key / openai package) — leaving roadmap as-is")
        print("  Set OPENAI_API_KEY and pip install openai for AI-powered roadmap updates")

    patched = patch_readme(current, table, new_roadmap)

    if patched != current:
        README_PATH.write_text(patched, encoding="utf-8")
        print(f"→ README updated — {len(patched)} chars")
        return 0
    else:
        print("→ README unchanged")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
