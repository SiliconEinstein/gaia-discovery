#!/usr/bin/env python3
"""Use Gemini-3.1-pro (via OpenAI-compatible API) to review a file.

Generic version — auto-reads CLAUDE.md for project context.

Usage:
    python review_gemini.py                  # review README.md
    python review_gemini.py path/to/file.md
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
import re

MAX_RETRIES = 5
RETRY_DELAY = 10  # seconds, multiplied by attempt number

MODEL = "Vendor2/Gemini-3.1-pro"


def _find_project_context():
    """Walk up from cwd to find CLAUDE.md and extract Project Overview."""
    d = os.getcwd()
    for _ in range(10):
        claude_md = os.path.join(d, "CLAUDE.md")
        if os.path.isfile(claude_md):
            with open(claude_md, "r", encoding="utf-8") as f:
                text = f.read()
            # Extract "## Project Overview" section
            m = re.search(
                r"##\s*Project Overview\s*\n(.*?)(?=\n##\s|\Z)",
                text,
                re.DOTALL,
            )
            if m:
                return m.group(1).strip()
            # Fallback: first 500 chars
            return text[:500].strip()
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.basename(os.getcwd())


def main():
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        sys.exit(1)

    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL", "https://api.openai.com")
    ).rstrip("/")
    # GPUGeek base URL already includes /v1 — avoid doubling it (pitfall-004)
    if base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"

    file_path = sys.argv[1] if len(sys.argv) > 1 else "README.md"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: {file_path} not found")
        sys.exit(1)

    project_ctx = _find_project_context()

    system_prompt = f"""\
You are reviewing a file from this project:
{project_ctx}

Before reviewing technical details, first assess:
1. Is this needed at all? Could a simpler approach work?
2. Is this over-engineered or prematurely abstracted?
3. Are resource costs (disk/memory/time) considered?
4. Are parameter choices explained from first principles, not just copied?

Then provide a technical review with concrete improvement suggestions.
Structure your response as:
- Necessity Assessment (is this the right thing to build?)
- Design Quality (is it built right?)
- Specific Improvements (concrete suggestions)"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Review this file:\n\n{content}"},
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    print(f"Reviewing : {file_path}")
    print(f"Model     : {MODEL}")
    print(f"Endpoint  : {url}")
    print(f"Context   : {project_ctx[:80]}...")
    print("=" * 60)

    data = json.dumps(payload).encode("utf-8")

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                usage = body.get("usage", {})
                print(f"Tokens    : {usage.get('prompt_tokens', '?')} in / "
                      f"{usage.get('completion_tokens', '?')} out")
                print("=" * 60)
                print()
                for choice in body.get("choices", []):
                    msg = choice.get("message", {})
                    print(msg.get("content", ""))
                return
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            retryable = (
                (e.code == 400 and ("饱和" in error_body or "overloaded" in error_body.lower()))
                or e.code == 429
            )
            if retryable and attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt  # exponential-ish backoff
                print(f"[Attempt {attempt}/{MAX_RETRIES}] {e.code} — retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"HTTP Error: {e.code} {e.reason}")
            print(error_body)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"URL Error: {e.reason}")
            sys.exit(1)


if __name__ == "__main__":
    main()
