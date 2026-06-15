#!/usr/bin/env python3
"""
pre-push secrets check — scans the diff being pushed for sensitive content.

Uses the same DeepSeek API key as update-readme.py (DEEPSEEK_API_KEY).
If suspicious patterns are found, the push is blocked.

Sensitive = hardcoded API keys, secret tokens, local paths revealing
  filesystem structure (e.g. /home/username), private IPs, credentials.

Resolution order:
  1. DEEPSEEK_API_KEY env var
  2. .env file in repo root (DEEPSEEK_API_KEY=xxx)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


# ── API key resolution ───────────────────────────────────────────────

def _resolve_api_key() -> str | None:
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


# ── Get the diff ─────────────────────────────────────────────────────

def get_push_diff() -> str | None:
    """Return the diff of commits that would be pushed (vs origin/main)."""
    try:
        subprocess.run(
            ["git", "rev-parse", "origin/main"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError:
        print("⚠️  origin/main not found — can't compute diff, skipping secrets check")
        return None

    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"⚠️  git diff failed (rc={result.returncode}): {result.stderr.strip()}")
        return None

    diff = result.stdout.strip()
    if not diff:
        print("→ nothing to diff — skipping secrets check")
        return None

    return diff


def get_staged_diff() -> str | None:
    """Fallback: return staged diff (for local testing without origin)."""
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True, text=True, timeout=30,
    )
    content = result.stdout.strip()
    return content or None


# ── Regex fallback checks ────────────────────────────────────────────

def regex_quick_check(diff: str) -> list[str]:
    """Basic regex checks as a safety net. Returns list of findings."""
    findings: list[str] = []
    lines = diff.split("\n")

    for i, line in enumerate(lines):
        if line.startswith("-") or line.startswith("@@"):
            continue
        if not line.startswith("+"):
            continue

        content = line[1:]

        # API key patterns (sk-... >= 20 chars)
        if re.search(r'sk-[a-zA-Z0-9]{20,}', content):
            findings.append(f"Hardcoded API key (sk-...) near line {i+1}")
            break

        # Local home paths
        if re.search(r'/home/(?!nobody|www)[a-z]/', content) or \
           re.search(r'/Users/[A-Za-z]/', content):
            findings.append(f"Local filesystem path with username near line {i+1}")

        # Private IPs
        if re.search(
            r'(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
            r'192\.168\.\d{1,3}\.\d{1,3}|'
            r'172\.(?:1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})',
            content,
        ):
            findings.append(f"Private IP address near line {i+1}")

    return findings


# ── LLM secrets check ────────────────────────────────────────────────

DEEPSEEK_BASE = "https://api.deepseek.com"


def check_diff_with_llm(diff: str) -> str | None:
    """
    Send diff to DeepSeek for review.
    Returns an error message if secrets are found, or None if clean.
    """
    api_key = _resolve_api_key()
    if not api_key:
        print("→ no DEEPSEEK_API_KEY available — skipping LLM secrets check")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        print("→ openai package not installed — skipping LLM secrets check")
        return None

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE)

    system_prompt = (
        "You are a security reviewer. Given a git diff (code changes about to be pushed), "
        "check for any sensitive or secret content that should NOT be committed:\n\n"
        "🚫 FLAG THESE:\n"
        "- Hardcoded API keys, tokens, passwords (patterns like sk-..., gh[psu]_..., etc.)\n"
        "- Local filesystem paths with usernames (e.g. /home/cutuy/, /Users/jason/)\n"
        "- Private IP addresses (10.x.x.x, 172.16-31.x.x, 192.168.x.x)\n"
        "- SSH private keys or certificate content\n"
        "- Database connection strings with credentials\n"
        "- AWS/GCP/Azure access keys or secret keys\n"
        "- Any environment-specific absolute paths\n\n"
        "✅ IGNORE:\n"
        "- Placeholder text like `***`, `sk-...`, `your-api-key`, `{env:...}`\n"
        "- Example paths like `/path/to/repo` or `/example/`\n"
        "- Test fixtures meant to look like secrets\n\n"
        "Respond with one of:\n"
        "SAFE\n"
        "or\n"
        "UNSAFE: <brief explanation of what was found and which file/line>\n\n"
        "If UNSAFE, include the file path and approximate line number."
    )

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Review this diff:\n\n{diff}"},
            ],
            temperature=0.1,
            max_tokens=300,
        )
    except Exception as e:
        print(f"⚠️  LLM call failed: {e}")
        return None

    content = resp.choices[0].message.content
    if not content:
        return None

    content = content.strip()
    if content.startswith("SAFE"):
        return None
    if content.startswith("UNSAFE"):
        return content
    print(f"→ LLM returned ambiguous response, treating as safe: {content[:100]}")
    return None


# ── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    diff = get_push_diff()

    # Fallback to staged diff if no origin comparison available
    if diff is None:
        diff = get_staged_diff()

    if diff is None:
        print("→ no diff to check")
        return 0

    # 1. Regex quick check (fast, no API call needed)
    regex_hits = regex_quick_check(diff)
    if regex_hits:
        for hit in regex_hits:
            print(f"❌ {hit}")
        print()
        print("Push ABORTED — remove sensitive content before pushing.")
        return 1

    # 2. LLM deep check (catches pattern-based and contextual secrets)
    llm_result = check_diff_with_llm(diff)
    if llm_result:
        print(f"❌ Secrets check failed: {llm_result}")
        print()
        print("Push ABORTED — remove sensitive content before pushing.")
        return 1

    print("✓ secrets check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
