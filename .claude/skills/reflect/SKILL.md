---
name: reflect
description: "Extract lessons learned from the current session and write them to structured memory files. This is the critical feedback loop that makes the evolution system work. Use at session end, before wrap-up/merge. Trigger on: 'reflect', 'what did we learn', 'extract lessons', 'update memory', 'session end', or automatically as part of /wrap-up. Also use after fixing a non-trivial bug, resolving a merge conflict, or discovering an unexpected behavior — don't wait until session end if the lesson is fresh."
---

# /reflect — Session Knowledge Extraction

Extract lessons from the current session and persist them to `.claude/memory/` files. This is the **mandatory** feedback loop that turns one-off debugging into permanent project knowledge.

The argument provided is: $ARGUMENTS

## Why This Exists

Without /reflect, knowledge dies with the session. The same bugs get re-discovered, the same patterns get re-learned, and the evolution system is an empty shell. This skill is the write-side of the memory loop (session-start protocol is the read-side).

## Step 1 — Gather session context

Collect what happened this session:

```bash
# What files changed?
git diff main...HEAD --stat 2>/dev/null || git diff master...HEAD --stat

# What were the commits?
git log main...HEAD --oneline 2>/dev/null || git log master...HEAD --oneline

# Any error patterns in recent commands?
# (Review your conversation history for errors, surprises, workarounds)
```

Also mentally review:
- Bugs encountered and their root causes
- Unexpected behaviors or surprises
- Decisions made and why
- Patterns that worked well
- Things that took longer than expected (and why)

## Step 2 — Classify findings

For each finding, classify it into exactly one category:

| Category | File | Criteria |
|----------|------|----------|
| **Pitfall** | `pitfalls.yaml` | Something broke. You now know to avoid it. |
| **Pattern** | `patterns.yaml` | A multi-step workflow that should be followed consistently. |
| **Decision** | `decisions.yaml` | An architectural choice with trade-offs worth documenting. |
| **Review insight** | `review-insights.yaml` | A valuable observation from an external review (GPT, Gemini, human). |

**Quality bar**: Each entry must be:
1. **Actionable** — tells you what to do or not do
2. **Specific** — names files, functions, exact error messages
3. **Non-duplicate** — check existing entries first!

**Skip if**: The session was routine with no new lessons. Writing "everything went fine" is noise, not knowledge.

## Step 3 — Check for duplicates

Read existing memory files before writing:

```bash
cat .claude/memory/pitfalls.yaml
cat .claude/memory/patterns.yaml
cat .claude/memory/decisions.yaml
```

If a finding is already captured, **do not add a duplicate**. If the existing entry needs updating (e.g., a pitfall now has a better workaround), update it in-place.

## Step 4 — Write entries

Append new entries to the appropriate YAML file. Follow the existing format exactly:

### Pitfall format:
```yaml
- id: pitfall-NNN
  date: YYYY-MM-DD
  expires: YYYY-MM-DD  # +3 months from date
  title: "Short description of what went wrong"
  wrong: "The thing that caused the problem"
  right: "The correct approach"
  impact: "What symptom appeared (error message, wrong behavior)"
  files: [server/routes/example.py]
  tags: [backend, api]
```

### Pattern format:
```yaml
- id: pattern-NNN
  date: YYYY-MM-DD
  expires: YYYY-MM-DD  # +6 months from date
  title: "Name of the workflow"
  steps:
    - "Step 1"
    - "Step 2"
  tags: [category]
```

### Decision format:
```yaml
- id: decision-NNN
  date: YYYY-MM-DD
  expires: YYYY-MM-DD  # +6 months from date
  title: "What was decided"
  choice: "The chosen approach"
  alternatives_considered:
    - "Alternative 1 — why rejected"
  trade_off: "Known downside"
  files: [affected/files.py]
  tags: [category]
```

## Step 5 — Update skill CHANGELOGs (if applicable)

If you used any `.claude/skills/*/SKILL.md` during this session and encountered an issue or learned something about it:

1. Open that skill's `CHANGELOG.md`
2. Add a usage log entry under `## Usage Log`:
   ```markdown
   ### YYYY-MM-DD — <brief context>
   - **Context**: What you were doing
   - **Issue**: What went wrong (or "None" if smooth)
   - **Resolution**: How you fixed it
   - **Suggestion**: How the skill could be improved (if any)
   ```
3. If this suggestion matches an existing one in `## Pending Amendment Proposals`, increment its confirmation count.

## Step 6 — Sync to auto-memory

Update the Claude Code auto-memory file so the next session gets critical pitfalls natively in context:

```
~/.claude/projects/<project-path>/memory/MEMORY.md
```

If any **new pitfall** was added, append a one-liner to the `## Critical Pitfalls` section of MEMORY.md. Keep MEMORY.md under 200 lines — if it's getting long, remove the oldest/least-important entry.

## Step 7 — Generalize (the "举一反三" step)

**This is the most important step.** For each finding, ask:

> "Does this same class of problem exist elsewhere in the codebase?"

Examples:
- Found a missing agent .md file → Check ALL agent .md files, not just the reported one
- Found a route missing tests → Check ALL routes for test coverage
- Found a model column not in migration → Check ALL columns across ALL models
- Found a stale number in CLAUDE.md → Run `check_invariants.py --fix` to catch ALL drift

If generalization reveals additional issues, either:
- Fix them now (if quick)
- Add them as new pitfall entries (if they need separate sessions)
- Flag them to the user (if they require discussion)

**Never write a pitfall that's specific to one instance when the underlying pattern is general.**

## Anti-patterns

- **Don't write entries for trivial things** — "renamed a variable" is not a pitfall
- **Don't duplicate existing entries** — always check first
- **Don't write vague entries** — "be careful with APIs" is useless; "GPUGeek base_url already includes /v1, don't add /v1/chat/completions" is useful
- **Don't skip the generalize step** — it's the difference between fixing one bug and preventing a class of bugs
- **Don't batch this with wrap-up** — /reflect should be lightweight and fast (< 2 minutes); if you're spending more time, you're over-writing

## Output

After completing, display a brief summary:

```
Reflect complete:
  + N new pitfall(s)
  + N new pattern(s)
  + N new decision(s)
  ~ N CHANGELOG update(s)
  → N generalized finding(s)
```
