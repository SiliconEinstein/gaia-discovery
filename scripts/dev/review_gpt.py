#!/usr/bin/env python3
"""Use GPT-5.4 (via GPUGeek predictions API) to review a file.

Generic version — auto-reads CLAUDE.md for project context.

Usage:
    python review_gpt.py                  # review README.md
    python review_gpt.py path/to/file.md
"""

import os
import sys
import json
import urllib.request
import urllib.error
import re

MODEL = "Vendor2/GPT-5.4"
URL = "https://api.gpugeek.com/predictions"


def _find_project_context():
    """Walk up from cwd to find CLAUDE.md and extract Project Overview."""
    d = os.getcwd()
    for _ in range(10):
        claude_md = os.path.join(d, "CLAUDE.md")
        if os.path.isfile(claude_md):
            with open(claude_md, "r", encoding="utf-8") as f:
                text = f.read()
            m = re.search(
                r"##\s*Project Overview\s*\n(.*?)(?=\n##\s|\Z)",
                text,
                re.DOTALL,
            )
            if m:
                return m.group(1).strip()
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

Then provide a creative review — suggest alternative approaches, novel simplifications,
or unconventional improvements. Think outside the box.
Structure your response as:
- Necessity Assessment (is this the right thing to build?)
- Creative Alternatives (what else could work?)
- Specific Improvements (concrete suggestions)"""

    prompt = system_prompt + "\n\nReview this file:\n\n" + content
    payload = {
        "model": MODEL,
        "input": {
            "prompt": prompt,
            "max_tokens": 4096,
            "temperature": 0.3,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    print(f"Reviewing : {file_path}")
    print(f"Model     : {MODEL}")
    print(f"Endpoint  : {URL}")
    print(f"Context   : {project_ctx[:80]}...")
    print("=" * 60)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            output = body.get("output", "")
            metrics = body.get("metrics", {})
            if metrics:
                pt = metrics.get("input_token_count", "?")
                ct = metrics.get("output_token_count", "?")
                print(f"Tokens    : {pt} in / {ct} out")
            print("=" * 60)
            print()
            if isinstance(output, str):
                print(output)
            elif isinstance(output, list):
                for item in output:
                    print(item if isinstance(item, str) else json.dumps(item))
            else:
                print(json.dumps(output, indent=2))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP Error: {e.code} {e.reason}")
        print(error_body)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
