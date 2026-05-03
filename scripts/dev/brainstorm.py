#!/usr/bin/env python3
"""Multi-model brainstorm: run N models in parallel, collect + summarize.

Usage:
    python brainstorm.py <file> [--role <role>] [--style <style>]

Roles: reviewer (default), scientist, community-builder, red-team, visionary
Styles: review (default), brainstorm, critique, debate

Models are defined in MODELS list below. Failed models are skipped gracefully.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Model registry ─────────────────────────────────────────────────
# Each model has: name, endpoint format, API config
# Format: "chat" = OpenAI chat completions, "predictions" = GPUGeek predictions

MODELS = [
    {
        "name": "Claude-Opus-4.6",
        "model_id": "Vendor2/Claude-4.6-opus",
        "format": "predictions",
        "url": "https://api.gpugeek.com/predictions",
        "max_tokens": 4096,
        "timeout": 180,
    },
    {
        "name": "GPT-5.4",
        "model_id": "Vendor2/GPT-5.4",
        "format": "predictions",
        "url": "https://api.gpugeek.com/predictions",
        "max_tokens": 4096,
        "timeout": 180,
    },
    {
        "name": "Gemini-3.1-pro",
        "model_id": "Vendor2/Gemini-3.1-pro",
        "format": "chat",
        "url": "https://api.gpugeek.com/v1/chat/completions",
        "max_tokens": 4096,
        "timeout": 180,
        "fallback": {
            "name": "Gemini-3-flash",
            "model_id": "Vendor2/Gemini-3-flash",
            "format": "predictions",
            "url": "https://api.gpugeek.com/predictions",
            "max_tokens": 4096,
            "timeout": 180,
        },
    },
    {
        "name": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "url": "https://api.gpugeek.com/predictions",
        "max_tokens": 4096,
        "timeout": 180,
    },
    {
        "name": "Kimi-k2.5",
        "model_id": "Vendor3/kimi-k2.5",
        "format": "predictions",
        "url": "https://api.gpugeek.com/predictions",
        "max_tokens": 4096,
        "timeout": 300,  # Kimi is slower, needs longer timeout
    },
]

MAX_RETRIES = 3
RETRY_DELAY = 10

# ── Role personas ──────────────────────────────────────────────────

ROLE_PROMPTS = {
    "reviewer": (
        "You are a senior technical reviewer. "
        "Assess necessity, design quality, and provide concrete improvements."
    ),
    "scientist": (
        "You are a working scientist (PI-level) who needs reproducibility tools urgently. "
        "You have limited time, many grad students, and care about: will this help me publish? "
        "Will it save my lab time? Is the data trustworthy?"
    ),
    "community-builder": (
        "You are an experienced community builder who has seen platforms thrive and die "
        "(StackOverflow, Reddit, Discourse, Papers with Code). "
        "You care about: cold-start problem, retention, network effects, moderation, "
        "and what makes people come back every week."
    ),
    "red-team": (
        "You are a red-team adversary. Your job is to break this, find fatal flaws, "
        "identify what will go wrong first, and expose hidden assumptions. "
        "Be relentless but constructive — every attack comes with a defense suggestion."
    ),
    "visionary": (
        "You are a visionary scientific community architect. "
        "Think 5 years ahead. What paradigm shifts are coming? "
        "How should this platform position itself? Be bold and unconventional."
    ),
    "agent-developer": (
        "You are an AI agent developer who wants to build agents that participate in science. "
        "You care about: API design, structured data, evaluation sandboxes, "
        "trace format quality, and what makes agent contributions genuinely useful."
    ),
    "grad-student": (
        "You are a first-year or second-year graduate student, overwhelmed and sleep-deprived. "
        "Your advisor just told you to reproduce a paper by next week. You have never set up "
        "a simulation environment before. You care about: is this easy to start? Will I get "
        "stuck on installation? Can I finish before the group meeting? Will this make me look "
        "competent in front of my PI? You are honest about confusion, allergic to jargon, "
        "and will immediately abandon anything that takes more than 30 minutes to set up."
    ),
    "acg": (
        "You are a passionate ACG (Anime/Comic/Game) otaku who also happens to be a talented "
        "developer. You think in terms of character arcs, gacha mechanics, achievement systems, "
        "and narrative hooks. You evaluate everything through the lens of: is this fun? Does it "
        "have 'progression feel' (成长感)? Would I grind this at 2am? Can I show off my rank to "
        "friends? You speak with enthusiasm, use metaphors from anime/games freely, and believe "
        "that if a platform isn't emotionally engaging, no amount of scientific rigor will save it. "
        "You care deeply about: visual polish, collectibles (badges, skins, titles), seasonal events, "
        "community rituals, and the dopamine loop. Think of this as designing a science gacha game."
    ),
}

# ── Style modifiers ────────────────────────────────────────────────

STYLE_PROMPTS = {
    "review": (
        "Structure your response as:\n"
        "- Necessity Assessment (is this the right thing to build?)\n"
        "- Design Quality (is it built right?)\n"
        "- Specific Improvements (concrete suggestions)"
    ),
    "brainstorm": (
        "Structure your response as:\n"
        "- What is Right (keep these)\n"
        "- What is Missing (critical gaps)\n"
        "- Bold Ideas (unconventional suggestions to accelerate)\n"
        "- Priority Reordering (if any milestones should swap or merge)"
    ),
    "critique": (
        "Structure your response as:\n"
        "- Fatal Flaws (what will kill this project)\n"
        "- Hidden Assumptions (what is being taken for granted)\n"
        "- Uncomfortable Questions (what no one is asking)\n"
        "- Rescue Plan (how to fix the above)"
    ),
    "debate": (
        "Take a CONTRARIAN position. Argue AGAINST the current approach. "
        "Even if you think it's good, find the strongest possible counterarguments. "
        "Structure as:\n"
        "- The Strongest Case Against\n"
        "- What the Authors Don't Want to Hear\n"
        "- The Alternative They Should Consider\n"
        "- One Thing That Would Change Your Mind"
    ),
}


def _find_project_context():
    """Walk up from cwd to find CLAUDE.md and extract Project Overview."""
    d = os.getcwd()
    for _ in range(10):
        claude_md = os.path.join(d, "CLAUDE.md")
        if os.path.isfile(claude_md):
            with open(claude_md, "r", encoding="utf-8") as f:
                text = f.read()
            m = re.search(
                r"##\s*Project Overview\s*\n(.*?)(?=\n##\s|\Z)", text, re.DOTALL
            )
            if m:
                return m.group(1).strip()
            return text[:500].strip()
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.basename(os.getcwd())


def _call_single(model_cfg, prompt, api_key):
    """Call a single model config (no fallback). Returns (name, text, tokens) or (name, None, None)."""
    name = model_cfg["name"]
    fmt = model_cfg["format"]

    if fmt == "predictions":
        payload = json.dumps({
            "model": model_cfg["model_id"],
            "input": {
                "prompt": prompt,
                "max_tokens": model_cfg["max_tokens"],
                "temperature": 0.5,
            },
        }).encode()
    else:  # chat completions
        payload = json.dumps({
            "model": model_cfg["model_id"],
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": model_cfg["max_tokens"],
            "temperature": 0.5,
        }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(
            model_cfg["url"], data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=model_cfg["timeout"]) as resp:
                data = json.loads(resp.read().decode())

                if fmt == "predictions":
                    output = data.get("output", "")
                    if isinstance(output, list):
                        text = output[0] if output else ""
                    else:
                        text = str(output)
                    tokens = data.get("metrics", {})
                    tok_in = tokens.get("input_token_count", "?")
                    tok_out = tokens.get("output_token_count", "?")
                else:
                    text = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {})
                    tok_in = tokens.get("prompt_tokens", "?")
                    tok_out = tokens.get("completion_tokens", "?")

                return name, text.strip(), f"{tok_in} in / {tok_out} out"

        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            retryable = e.code == 429 or (
                e.code == 400
                and ("overloaded" in err.lower() or "饱和" in err)
            )
            if retryable and attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                print(f"  [{name}] Attempt {attempt}/{MAX_RETRIES} — {e.code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"  [{name}] Failed: HTTP {e.code}")
            return name, None, None
        except Exception as e:
            print(f"  [{name}] Failed: {e}")
            return name, None, None

    return name, None, None


def _call_model(model_cfg, prompt, api_key):
    """Call a model with optional fallback. Returns (display_name, text, tokens)."""
    name, text, tokens = _call_single(model_cfg, prompt, api_key)
    if text:
        return name, text, tokens

    # Try fallback if available
    fallback = model_cfg.get("fallback")
    if fallback:
        print(f"  [{name}] Trying fallback → {fallback['name']}...")
        return _call_single(fallback, prompt, api_key)

    return name, None, None


def main():
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        print("Error: set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        sys.exit(1)

    # Parse args
    file_path = None
    role = "reviewer"
    style = "review"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--role" and i + 1 < len(args):
            role = args[i + 1]
            i += 2
        elif args[i] == "--style" and i + 1 < len(args):
            style = args[i + 1]
            i += 2
        else:
            file_path = args[i]
            i += 1

    if not file_path:
        file_path = "README.md"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: {file_path} not found")
        sys.exit(1)

    if role not in ROLE_PROMPTS:
        print(f"Error: unknown role '{role}'. Available: {', '.join(ROLE_PROMPTS)}")
        sys.exit(1)
    if style not in STYLE_PROMPTS:
        print(f"Error: unknown style '{style}'. Available: {', '.join(STYLE_PROMPTS)}")
        sys.exit(1)

    project_ctx = _find_project_context()

    # Build prompt
    prompt = (
        f"Project context:\n{project_ctx}\n\n"
        f"Your role:\n{ROLE_PROMPTS[role]}\n\n"
        f"{STYLE_PROMPTS[style]}\n\n"
        f"Review this file ({file_path}):\n\n{content}"
    )

    n_models = len(MODELS)
    print(f"Brainstorm : {file_path}")
    print(f"Role       : {role}")
    print(f"Style      : {style}")
    print(f"Models     : {', '.join(m['name'] for m in MODELS)} ({n_models} total)")
    print("=" * 60)

    # Run all models in parallel
    results = []
    with ThreadPoolExecutor(max_workers=n_models) as pool:
        futures = {
            pool.submit(_call_model, m, prompt, api_key): m["name"]
            for m in MODELS
        }
        for future in as_completed(futures):
            name, text, tokens = future.result()
            results.append((name, text, tokens))

    # Print results
    successes = [(n, t, tok) for n, t, tok in results if t]
    failures = [n for n, t, _ in results if not t]

    for name, text, tokens in successes:
        print(f"\n{'━' * 60}")
        print(f"  {name}  ({tokens})")
        print(f"{'━' * 60}\n")
        print(text)

    if failures:
        print(f"\n{'━' * 60}")
        print(f"  ⚠ Failed models: {', '.join(failures)}")
        print(f"{'━' * 60}")

    print(f"\n{'=' * 60}")
    print(f"Summary: {len(successes)}/{n_models} models responded")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
