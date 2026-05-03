---
name: brainstorm
description: "Run a multi-model brainstorm on a file using GPT-5.4, Gemini-3.1-pro (fallback: 3-flash), Qwen-3.5-plus, and Kimi-k2.5 in parallel. Supports different reviewer roles (scientist, community-builder, red-team, visionary, agent-developer) and styles (review, brainstorm, critique, debate). Use when you want diverse perspectives from multiple AI models. Accepts: <file> [--role <role>] [--style <style>]."
---

# Multi-Model Brainstorm

Run multiple LLM models in parallel to review/brainstorm a file from different perspectives.

The argument provided is: $ARGUMENTS

## Step 1 — Parse arguments and run the script

Run the brainstorm script with the provided arguments:

```bash
python3 scripts/dev/brainstorm.py $ARGUMENTS
```

### Available roles (--role)
| Role | Perspective |
|------|------------|
| `reviewer` | Senior technical reviewer (default) |
| `scientist` | Working PI who needs reproducibility tools |
| `community-builder` | Experienced platform builder (StackOverflow, Reddit) |
| `red-team` | Adversary finding fatal flaws |
| `visionary` | 5-year-ahead strategic thinker |
| `agent-developer` | AI agent developer wanting to participate in science |

### Available styles (--style)
| Style | Output structure |
|-------|-----------------|
| `review` | Necessity → Design Quality → Improvements (default) |
| `brainstorm` | What's Right → Missing → Bold Ideas → Priority Reordering |
| `critique` | Fatal Flaws → Hidden Assumptions → Uncomfortable Questions → Rescue |
| `debate` | Contrarian position — strongest case against the current approach |

### Examples

```bash
# Default review of README
python3 scripts/dev/brainstorm.py README.md

# Brainstorm the roadmap from a scientist's perspective
python3 scripts/dev/brainstorm.py docs/ROADMAP.md --role scientist --style brainstorm

# Red-team critique of the API design
python3 scripts/dev/brainstorm.py server/routes/challenges.py --role red-team --style critique

# Debate: argue against the current architecture
python3 scripts/dev/brainstorm.py CLAUDE.md --role visionary --style debate
```

## Step 2 — Present results

Show the full output from all models. Then synthesize:
1. **Consensus** — what do all models agree on?
2. **Unique insights** — what did only one model suggest?
3. **Conflicts** — where do models disagree? Which position is stronger?
4. **Action items** — concrete next steps based on the synthesis

## Step 3 — If the script fails

If `scripts/dev/brainstorm.py` is missing, fall back to running individual reviews:
```bash
python3 scripts/dev/review_gpt.py <file>
python3 scripts/dev/review_gemini.py <file>
```
And manually call Qwen via the predictions API.
