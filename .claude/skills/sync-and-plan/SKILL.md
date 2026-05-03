---
name: sync-and-plan
description: "Pull updates from master, read trace shards and coordination state across all worktrees, and propose what to work on next. Use this skill whenever the user says 'sync', 'what should I work on', 'what changed', 'catch me up', 'what happened', 'plan next steps', 'show me TODOs', 'what needs doing', 'status update', 'what branches are active', 'pull from master', 'sync and plan', 'next steps', or wants to understand the current state of the project across worktrees before starting work. Also use at the beginning of a new session when the user wants to orient themselves, or when they ask 'what did the other worktrees do', 'any updates', or 'what was merged recently'."
---

# Sync and Plan

Orient yourself in a multi-worktree project: pull the latest from master, read what happened across all branches, and surface actionable next steps.

This skill exists because the project is developed by multiple independent Claude Code sessions in separate git worktrees. Each session has its own context and can't see what others are doing. Running this skill at the start of a session (or after being away) closes that visibility gap fast.

The argument provided is: $ARGUMENTS

## Step 1 — Pull updates from master

Sync the current branch with the latest master so you're working on top of the most recent code.

1. Check current branch and worktree status:
   ```bash
   git branch --show-current
   git worktree list
   git status --short
   ```

2. Determine the main branch name:
   ```bash
   git rev-parse --verify main 2>/dev/null && echo "main" || echo "master"
   ```

3. Fetch and merge master into the current branch:
   ```bash
   git fetch origin
   git merge origin/<main-branch> --no-edit
   ```
   If there are merge conflicts, **stop and report them** — do not auto-resolve. List the conflicting files and let the user decide how to proceed.

4. Show what came in:
   ```bash
   git log --oneline HEAD@{1}..HEAD   # new commits pulled in
   ```

## Step 2 — Read the trace index

The trace index (`trace/master.md`) is a reverse-chronological log of everything merged to master. Read it to understand what happened recently.

```bash
cat trace/master.md
```

Summarize the most recent 3-5 merge entries for the user, focusing on:
- What features/fixes were added
- Which branches delivered them
- Any patterns (e.g., "three branches all touched the chrome extension this week")

## Step 3 — Read coordination state across all worktrees

Each worktree publishes its status to `.claude/coordination/state/<branch>.json`. These files contain what the branch is doing, what files it touches, and what it plans to do next.

```bash
ls .claude/coordination/state/
```

Read every state file. For each worktree, extract:
- `branch` and `purpose` — what it's for
- `status` — `idle`, `active`, `ready`, `merged`
- `readyToMerge` — is it waiting to be merged?
- `accomplishments` — what it finished
- `nextAction` — what it planned to do next but may not have done yet
- `touching` — files it modifies (useful for conflict awareness)

## Step 4 — Read relevant trace shards

For any worktree whose state is `idle` or `active` (i.e., not yet merged), read its trace shard at `trace/<branch>.md` if one exists. These contain detailed session notes, decisions, and unfinished work.

Look specifically for:
- Unfinished tasks or "next steps" mentioned but not completed
- Open questions or decisions that were deferred
- Blockers that were identified but not resolved
- TODOs embedded in the narrative

## Step 5 — Check for stale worktrees

A worktree is "stale" if:
- Its state file says `readyToMerge: true` but it hasn't been merged
- Its state file says `status: idle` and the `lastUpdate` is more than 2 days old
- It has 0 commits ahead of master (`git rev-list --count <main>..<branch>`)
- The worktree directory exists but has no state file

Report stale worktrees so the user can decide whether to clean them up or resume work.

```bash
git worktree list
```

For each worktree branch, check how far ahead it is:
```bash
git rev-list --count origin/<main>..<branch>
```

## Step 6 — Surface TODOs and unfinished work

Collect all actionable items from:

1. **Coordination state `nextAction` fields** — things branches planned but didn't finish
2. **Trace shard narrative** — deferred decisions, open questions, blockers
3. **Code TODOs** — search for TODO/FIXME/HACK/XXX comments in recently changed files:
   ```bash
   git diff --name-only origin/<main>..HEAD | head -50
   ```
   Then grep those files for TODO markers.
4. **`readyToMerge` branches** — branches that are done and just need someone to merge them

## Step 7 — Propose next steps

Based on everything gathered, propose 3-5 concrete next actions, prioritized by impact. For each:

- **What**: one-line description
- **Why**: what it unblocks or improves
- **Where**: which branch/worktree, or suggest creating a new one
- **Risk**: any files that overlap with active worktrees (check `touching` arrays)

Format the proposal as a numbered list, most impactful first. If the user provided arguments hinting at what they want to do, weight the proposal toward that direction.

## Step 8 — Present the summary

Display a concise dashboard directly in the conversation. Use this format:

```
## Project Status

### Recently Merged
- <branch> (<date>): <1-line summary>
- ...

### Active Worktrees
| Branch | Purpose | Status | Ahead | Next Action |
|--------|---------|--------|-------|-------------|
| ...    | ...     | ...    | ...   | ...         |

### Unfinished Work / TODOs
1. <item> — from <source>
2. ...

### Proposed Next Steps
1. **<action>** — <why> (branch: <where>)
2. ...
```

Keep the whole summary scannable — a developer should be able to read it in 30 seconds and know exactly where the project stands and what to do next.

## Safety Rules

- Never force-push or reset branches.
- Never auto-resolve merge conflicts — report them and stop.
- Never delete worktrees or branches — only suggest cleanup.
- Never modify coordination state files for other worktrees — only read them.
- If `$ARGUMENTS` contains "no pull" or "skip pull", skip Step 1 entirely (useful when offline or when you just want the status without changing anything).
