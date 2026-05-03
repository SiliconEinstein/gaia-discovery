---
name: wrap-up
description: "Wrap up the current feature branch: discover and update relevant documentation, commit uncommitted changes, merge to the main branch, and optionally push. Use this skill whenever the user says 'wrap up', 'merge to main', 'finalize branch', 'finish this work', 'commit and merge', 'done with this feature', or wants to close out a feature branch. Also use when they ask to 'update docs and merge', 'finalize changes', or reference completing a task and merging back to main/master. Accepts optional arguments: a branch name, and/or 'push' to push after merge."
---

# Wrap Up Feature Branch

Finalize the current feature branch by discovering what changed, updating relevant documentation, committing, merging, and reporting.

The argument provided is: $ARGUMENTS

## Step 1 — Understand the current state

1. Run `git branch --show-current` to get the current branch.
   - If `$ARGUMENTS` names a different branch, use that.
   - If already on the main branch, abort: "Already on the main branch — nothing to merge."

2. Determine the main branch name. Check which exists:
   ```
   git rev-parse --verify main 2>/dev/null && echo "main"
   git rev-parse --verify master 2>/dev/null && echo "master"
   ```
   Use whichever resolves. If both exist, prefer `main`.

3. List what this branch adds over main:
   ```
   git log --oneline <main>..<branch>
   git diff --stat <main>..<branch>
   ```
   Show the commit list and changed-file summary to the user.

4. Check for uncommitted work:
   ```
   git status
   git diff --stat
   ```
   If there are unstaged or uncommitted changes, **commit them first** with a descriptive message matching the repo's style (check `git log --oneline -5` for conventions).

## Step 2 — Discover documentation to update

Do NOT assume any specific filenames. Instead, discover what exists:

1. **Find all markdown files** in the repo:
   ```
   find . -name '*.md' -not -path './.git/*' | sort
   ```

2. **Find all HTML files** that look like reports or summaries (not application code):
   ```
   find . -name '*.html' -not -path './.git/*' -not -path '*/node_modules/*' | sort
   ```

3. From these lists, identify documentation files that are likely candidates for update. Look for files whose names or content suggest they track:
   - Project status, progress, or implementation state
   - Summaries or overviews of what the project contains
   - Reports (especially HTML reports with timestamps)
   - READMEs at any level (root, subdirectories)

4. **Read each candidate file** to understand its purpose and current content. Decide whether the branch's changes warrant an update to that file:
   - Does the file reference features, tools, cases, or components that this branch added/changed?
   - Does the file have a date or timestamp that should be refreshed?
   - Does the file have a summary table, status list, or directory tree that is now stale?

5. **Skip files that are unaffected.** If a branch only added a visualization tool, a benchmark results table doesn't need changes unless the tool is listed in an infrastructure/tools section.

## Step 3 — Update discovered documentation

For each file identified as needing an update:

1. **Read the file fully** to understand its structure and formatting conventions.
2. **Make minimal, targeted edits** — only change sections affected by the branch. Do not reformat or rewrite unrelated content.
3. **Match the existing style exactly** — heading levels, bullet styles, table alignment, badge format, date format. Mimic what's already there.
4. For HTML files: preserve all CSS and structural markup. Only change data content (text, numbers, dates, table rows).
5. For status/progress files: update dates, counts, tables, and section entries that reflect the branch's changes.
6. For READMEs: update directory trees, feature lists, or tool references if the branch added new directories or capabilities.

## Step 4 — Evaluate whether new skills are needed

If the branch introduced a new repeatable workflow (a new benchmark case, a new analysis tool, a new build/test process), check whether a Claude skill already exists for it under `.claude/skills/`.

Criteria for creating a new skill:
- The workflow has multiple steps that require domain knowledge.
- A user would want to invoke it by name in future sessions.
- It's not already covered by an existing skill.

If warranted, create `.claude/skills/<name>/SKILL.md` following the format of existing skills in the same directory. Keep the skill general — avoid hardcoding paths or filenames inside skills too.

## Step 5 — Commit documentation updates

1. Stage only the files that were actually changed:
   ```
   git add <changed-files>
   ```
2. Commit with a message summarizing the doc updates. Match the repo's commit message style.

## Step 6 — Run /reflect (mandatory)

Run the `/reflect` skill to extract session knowledge into `.claude/memory/` files. This is **not optional** — it is the critical feedback loop that makes the evolution system work.

If `/reflect` has already been run this session (check: were any `.claude/memory/*.yaml` files modified today?), skip this step.

## Step 7 — Pre-merge validation gate

1. **Detect conflicting files**:
   ```bash
   git diff --name-only <main>..<branch>
   ```
   Cross-reference against other worktree state files in `.claude/coordination/state/*.json` — check their `touching` arrays. If overlap exists, warn:
   ```
   Conflict Risk: trace.md also touched by vk/e42b-discussion-zone
   ```

2. **Auto-generate touching list**: Update the current worktree's state file with:
   ```bash
   git diff --name-only <main>..HEAD
   ```
   Write the result to `.claude/coordination/state/<branch>.json` `touching` field.

3. **Compute merge order recommendation** (if multiple branches are ready):
   - For each worktree state file with `readyToMerge: true`, count touching files
   - Recommend merging fewest-touching-files first
   - Display recommendation to user

4. **Run tests** if the `/test-suite` skill is available. At minimum run `pytest tests/` to ensure no regressions before merge.

5. **Run invariant checker** to validate project consistency:
   ```bash
   python scripts/check_invariants.py
   ```
   - If any `[FAIL]` checks appear, fix them before proceeding.
   - If `CLAUDE.MD DRIFT` is reported, run `python scripts/check_invariants.py --fix` to auto-correct.
   - If all checks pass with only `[WARN]`, proceed (warnings are advisory).

## Step 8 — Merge to main

1. Checkout the main branch:
   ```
   git checkout <main-branch>
   ```

2. Merge the feature branch:
   ```
   git merge <feature-branch>
   ```
   - Default: merge commit (not squash, not fast-forward-only).
   - If the user requests squash or fast-forward, respect that.
   - **If there are conflicts, STOP and report them to the user.** Do NOT auto-resolve.

3. Verify:
   ```
   git log --oneline -5
   ```

## Step 9 — Update coordination state

After a successful merge, update the worktree's state file:
1. Set `status` to `"merged"` and `readyToMerge` to `false`
2. Update `accomplishments` with final summary
3. Write the branch's trace shard (`trace/<branch>.md`) with a session-end entry
4. Update `trace/master.md` with a merge summary line

## Step 10 — Push (only if explicitly requested)

**Never push automatically.** Only push if:
- The user explicitly says "push", or
- `$ARGUMENTS` contains the word "push"

When pushing, determine the correct remote ref:
```
git remote -v
git push origin <main-branch>
```
If local main differs from remote tracking branch name (e.g., local `main` vs remote `master`), use:
```
git push origin <local-main>:<remote-main>
```

## Step 11 — Report summary

**IMPORTANT**: Display the summary directly in the conversation using a markdown code block, NOT by running bash commands. The user cannot see bash stdout in Claude Code interface.

Display the final summary in the conversation using this format (pure ASCII, 70-char alignment):

```
╔══════════════════════════════════════════════════════════════════════╗
║                    Branch Wrap-Up Complete                           ║
╠══════════════════════════════════════════════════════════════════════╣
║ Branch Info                                                          ║
╟──────────────────────────────────────────────────────────────────────╢
║ Source    | <branch-name>                                            ║
║ Target    | <main-branch>                                            ║
║ Commits   | <N> commits                                              ║
║ Status    | [x] Pushed to origin/<main-branch>                       ║
╠══════════════════════════════════════════════════════════════════════╣
║ Documentation Updates                                                ║
╟──────────────────────────────────────────────────────────────────────╢
║ [x] <file1>                                                          ║
║     - <what changed>                                                 ║
║ [x] <file2>                                                          ║
║     - <what changed>                                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║ Skills Created                                                       ║
╟──────────────────────────────────────────────────────────────────────╢
║ None                                                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║ Summary                                                              ║
╟──────────────────────────────────────────────────────────────────────╢
║ <1-3 sentence description of what this branch accomplished,          ║
║ wrapped to fit within 70 characters per line>                        ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Critical formatting rules:**
- Display this table directly in your response as a markdown code block
- DO NOT use bash echo/cat/printf commands - the user cannot see bash output
- Each content line between `║` symbols must be exactly 70 characters wide
- Use pure ASCII: `[x]` for checkmarks, `-` for bullets, `|` for separators
- Pad lines with spaces to reach exactly 70 characters before the closing `║`
- For multi-line sections, add one entry per file with proper indentation
- Wrap long text in Summary section to multiple lines, each exactly 70 characters wide
- Wrap long text in Summary section to multiple lines, each exactly 70 characters wide

## Safety rules

- **Never force-push.** Never use `--force` or `--force-with-lease`.
- **Never auto-resolve merge conflicts.** Report them and stop.
- **Never push unless explicitly asked.**
- **Never commit binary output files** (`.PLT`, `.exe`, `.o`, `.bin`) unless the user specifically requests it. Warn if such files appear in `git status`.
- **Never delete branches** unless the user asks. After merging, the feature branch still exists — the user can delete it themselves.
- **Preserve worktree state.** If running inside a git worktree, be aware that `git checkout` may behave differently. Run `git worktree list` first to understand the layout if checkout fails.
