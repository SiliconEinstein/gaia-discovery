---
name: worktree
description: "Manage git worktrees: view status dashboard, create new worktrees, clean up stale ones, merge worktree branches to master safely, and sync worktrees with master. Use this skill whenever the user says 'worktree status', 'clean worktrees', 'remove stale worktrees', 'merge worktree', 'sync worktree', 'worktree dashboard', 'how many worktrees', 'disk usage worktrees', 'add worktree', 'new worktree', or asks about worktree management, cleanup, or merging. Also triggers on: 'prune worktrees', 'stale branches', 'reclaim disk'. NOT for: switching into a worktree interactively (use tmux prefix+w) or exiting a worktree session (use ExitWorktree tool)."
---

# Worktree Manager

Manage git worktrees across the project — status, create, cleanup, merge, and sync.

The argument provided is: $ARGUMENTS

## Subcommands

Parse `$ARGUMENTS` to determine the action:
- Empty or `status` → Step 1 (Dashboard)
- `add <description>` → Step 2 (Create)
- `clean` → Step 3 (Cleanup)
- `merge [branch]` → Step 4 (Merge to master)
- `sync` → Step 5 (Sync from master)

---

## Step 1 — Status Dashboard

Show a comprehensive overview of all worktrees, combining git data with coordination state.

### 1a. Read coordination state (if available)

Check for per-worktree state files:
```bash
ls .claude/coordination/state/*.json 2>/dev/null
```

If files exist, read each one. These contain:
- `purpose`: What the worktree is working on
- `status`: active / idle / stale
- `touching`: Files/directories being modified (auto-detected from `git diff --name-only master...HEAD`)
- `accomplishments`: What was done
- `nextAction`: Recommended next step

### 1b. Collect git data

1. Get the main worktree path:
   ```bash
   git worktree list --porcelain | head -1 | sed 's/worktree //'
   ```

2. List all worktrees:
   ```bash
   git worktree list
   ```

3. For each worktree, collect:
   - **Ahead/behind master**: `git rev-list --left-right --count master...<branch>`
   - **Disk usage**: `du -sh <path>`
   - **Last commit date**: `git log -1 --format='%cr' <branch>`
   - **Uncommitted changes**: `git -C <path> diff --stat --cached` and `git -C <path> diff --stat`
   - **Touching files** (auto-detect): `git -C <path> diff --name-only master...HEAD`

4. Scan for orphaned directories not in `git worktree list`:
   ```bash
   ls -d .claude/worktrees/*/ /var/tmp/vibe-kanban/worktrees/*/ 2>/dev/null
   ```
   Compare against the worktree list. Flag orphans.

### 1c. Detect conflicts

Cross-reference the `touching` lists from all worktrees. If two or more worktrees touch the same file, flag it as a **potential merge conflict**:
```
Conflict Risk
─────────────
trace.md          → touched by: e42b-discussion-zone, f32a-playground-skill
CLAUDE.md         → touched by: 6dd7-zotero, e42b-discussion-zone
```

### 1d. Compute merge order

For branches that are ready to merge, recommend ordering by:
1. Fewest touching files (least conflict risk)
2. Fewest commits ahead (smallest diff)
3. Closest to master (least divergence)

This is computed live — no persistent merge-queue file needed.

### 1e. Display combined dashboard

Display a summary table **directly in chat** (NOT via bash echo):
```
Worktree Status
═══════════════
Branch                          | Ahead | Behind | Disk   | Last Commit | Purpose
--------------------------------|-------|--------|--------|-------------|--------
vk/f32a-playground-skill        |     3 |      0 | 1.1 GB | 10m ago     | Test suite + coordination
vk/e42b-discussion-zone         |     1 |      2 | 988 MB | 2h ago      | Engagement + Bohrium
...

Conflict Risk: trace.md (2 branches), CLAUDE.md (2 branches)
Recommended merge order: f32a → e42b → 6dd7

Total: N worktrees, X.X GB disk
Stale (0 ahead, fully merged): N
Orphaned directories: N
```

### 1f. Check for per-branch trace shards

Look for `trace/<branch>.md` files. If they exist, show a one-line summary of the latest entry from each to give quick context on what each worktree has been doing.

---

## Step 2 — Create New Worktree

Create a worktree following the project's vk/ naming convention.

1. Parse `<description>` from arguments. Sanitize: lowercase, replace spaces with hyphens, truncate to 20 chars.

2. Generate a 4-hex short ID:
   ```bash
   head -c 2 /dev/urandom | xxd -p
   ```

3. Set up paths:
   ```
   branch:  vk/{id}-{description}
   path:    /var/tmp/vibe-kanban/worktrees/{id}-{description}/{repo_name}
   ```
   where `repo_name` = basename of the main worktree (e.g., `asurf`).

4. Create the worktree:
   ```bash
   MAIN_DIR=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
   REPO_NAME=$(basename "$MAIN_DIR")
   WT_DIR="/var/tmp/vibe-kanban/worktrees/${ID}-${DESC}"
   WT_PATH="${WT_DIR}/${REPO_NAME}"
   mkdir -p "$WT_DIR"
   git -C "$MAIN_DIR" worktree add -b "vk/${ID}-${DESC}" "$WT_PATH"
   ```

5. Copy `.claude/settings.json` from main repo to worktree (ensures EARS hooks are active):
   ```bash
   cp "$MAIN_DIR/.claude/settings.json" "$WT_PATH/.claude/settings.json"
   ```

6. Report the created worktree path and branch name.

7. Create an initial coordination state file:
   ```bash
   cat > "$WT_PATH/.claude/coordination/state/vk-${ID}-${DESC}.json" << 'EOF'
   {
     "branch": "vk/${ID}-${DESC}",
     "purpose": "<description from arguments>",
     "status": "active",
     "touching": [],
     "lastUpdate": "<current ISO timestamp>",
     "readyToMerge": false,
     "accomplishments": [],
     "nextAction": "Begin work"
   }
   EOF
   ```

---

## Step 3 — Clean Stale Worktrees

Safely remove worktrees that have been fully merged to master.

1. Run `git worktree prune` to clean stale administrative entries.

2. For each non-main worktree, check:
   ```bash
   git rev-list --count master..<branch>
   ```

3. Categorize:
   - **Safe to remove** (0 commits ahead): list with disk usage
   - **Has unmerged work** (>0 ahead): list separately, do NOT auto-remove

4. Check for orphaned directories.

5. Show the removal plan and **ask for confirmation**.

6. For each confirmed removal:
   ```bash
   git worktree remove <path>
   git branch -d <branch>   # -d (not -D) ensures it's merged
   ```

7. For orphaned directories:
   ```bash
   rm -rf <orphaned-path>
   ```

**Safety**: NEVER remove a worktree with unmerged commits unless the user explicitly confirms.

---

## Step 4 — Merge Worktree Branch to Master

Merge a worktree's branch into master **without** `git checkout master`.

This is the most critical operation — it encodes the fix for the #1 recurring pitfall.

1. Determine the branch to merge:
   - If argument provides a branch name or path, use that
   - Otherwise, use the current branch (`git branch --show-current`)

2. Find the main worktree path:
   ```bash
   MAIN_DIR=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
   ```

3. Show what will be merged:
   ```bash
   git log --oneline master..<branch>
   ```
   If 0 commits ahead, report "Nothing to merge — branch is already up to date with master." and stop.

4. Check for uncommitted changes in the worktree. If any exist, warn and ask whether to commit first.

5. **Run the merge from the main worktree directory:**
   ```bash
   git -C "$MAIN_DIR" merge <branch>
   ```

6. If merge conflicts occur, **STOP and report**. Do NOT auto-resolve.

7. Report the result: "Merged `<branch>` → master (N commits)."

### Critical safety rules

- **NEVER** run `git checkout master` inside a worktree — this is the #1 recurring agent mistake
- **NEVER** force-push or use `--force`
- **NEVER** auto-resolve merge conflicts
- Always merge from the main checkout directory using `git -C`

---

## Step 5 — Sync Worktree from Master

Update the current worktree with the latest commits from master.

1. Confirm we are NOT in the main checkout:
   ```bash
   GIT_DIR=$(git rev-parse --git-dir)
   GIT_COMMON=$(git rev-parse --git-common-dir)
   ```
   If `$GIT_DIR` = `$GIT_COMMON`, we're in the main checkout — report "Already on main checkout, nothing to sync." and stop.

2. Show how far behind:
   ```bash
   BEHIND=$(git rev-list --count HEAD..master)
   git log --oneline HEAD..master
   ```

3. Merge master:
   ```bash
   git merge master
   ```

4. If conflicts, **STOP and report**. Do NOT auto-resolve.

5. Report: "Synced N commits from master into `<branch>`."
