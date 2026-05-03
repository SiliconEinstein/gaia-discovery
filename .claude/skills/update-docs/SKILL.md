---
name: update-docs
description: "Audit and synchronize all project documentation — both repo markdown files (README.md, CLAUDE.md, STYLE.md, docs/DEPLOY.md, trace.md) AND the web #docs page content (js/pages/docs.js) — with the actual codebase state. Use this skill whenever the user says 'update docs', 'sync docs', 'audit documentation', 'docs are out of date', 'fix the README', 'update CLAUDE.md', 'sync documentation', 'docs drift', 'refresh docs', or mentions that file counts, project structure trees, or feature lists are stale or wrong. Also use after adding new features, models, routes, or pages — anything that would make existing documentation inaccurate. Use when the user says 'check if docs are current', 'verify documentation', 'documentation audit', 'are the docs up to date', or before wrapping up a feature branch if docs haven't been updated yet."
---

# Update Docs

Audit and synchronize all project documentation with the actual codebase state.

## When to Use

- After adding new features (UGC, testing, deployment changes)
- After major refactoring or architecture changes
- When docs mention outdated file counts, missing directories, or stale patterns
- Before wrapping up feature branches
- When onboarding new contributors (ensure docs are accurate)

## Documentation Inventory

| File | Purpose | Key Sections |
|------|---------|--------------|
| `README.md` | Project overview, quick start, structure | Features, disciplines, project structure tree, skills/agents tables, contributing |
| `CLAUDE.md` | Agent instructions | Project overview, custom agents, design system ref, project structure, data architecture, key patterns, testing |
| `STYLE.md` | Design system | Aesthetic direction, color tokens, typography, component patterns, anti-patterns |
| `docs/DEPLOY.md` | Deployment guide | Quick deploy, architecture, manual steps, updating, monitoring, static-only mode, database migration |
| `trace.md` | Development trace | EARS progress entries (decisions, discoveries, dead ends) |
| `js/pages/docs.js` | Web `#docs` page content | DOC_CONTENT (core concept articles), DOC_DISC_CONTENT (discipline guides), SLUGS mapping |

## Workflow

### Step 1 — Audit current state

Check for common drift patterns:

```bash
# Count actual files
echo "Pages:" && ls js/pages/ | wc -l
echo "Models:" && ls server/models/*.py | grep -v __init__ | wc -l
echo "Routes:" && ls server/routes/*.py | grep -v __init__ | wc -l
echo "Tests:" && ls tests/*.py | wc -l
echo "Data files:" && ls data/*.json | wc -l

# Check for missing directories in docs
grep -r "tests/" README.md CLAUDE.md
grep -r "docs/" README.md CLAUDE.md
```

**Common gaps to look for:**
- Project structure trees missing `tests/`, `docs/`, `trace.md`
- File counts outdated (pages, models, routes, tests)
- New features not documented (UGC, testing, badges, stars, trending)
- Deployment changes not in DEPLOY.md (container support, migration)
- Missing component patterns in STYLE.md (UGC forms, badges, stars)

### Step 2 — Read all docs

Read the full content of:
- `README.md`
- `CLAUDE.md`
- `STYLE.md`
- `docs/DEPLOY.md`
- `trace.md` (check if latest EARS entry is recent)
- `js/pages/docs.js` (web `#docs` page — check if articles cover all current features)

### Step 3 — Update each doc

**README.md updates:**
- Project structure tree: add missing directories (`tests/`, `docs/`), enumerate page files (14), model files (15), route files (14), test files (13 + conftest + browser_test)
- Add Testing section with pytest + Playwright commands and coverage table
- Verify skills/agents tables match actual `.claude/skills/` and `.claude/agents/` directories
- Update feature list if new capabilities added

**CLAUDE.md updates:**
- Project structure tree: same as README, plus add `trace.md` at root level
- Add Testing section with key infrastructure patterns (conftest.py, browser_test.py)
- Update data architecture table if new JSON files added
- Update key patterns if new architectural decisions made

**STYLE.md updates:**
- Add component patterns for new UI features (UGC forms, badges, stars, trending cards, docs page layout)
- Ensure color tokens, typography, and anti-patterns are still accurate

**docs/DEPLOY.md updates:**
- Add pre-deploy testing section
- Update rsync excludes to include `tests/`, `.pytest_cache`, `pytest.ini`
- Add database migration section if `_migrate_columns()` exists in `server/app.py`
- Document container/non-systemd deployment if `setup.sh` has privilege fallback

**trace.md updates:**
- Add new EARS entry if significant work was done (use current timestamp, tag concepts)
- Keep entries concise — decisions, discoveries, dead ends only

**js/pages/docs.js updates (web `#docs` page):**

The `#docs` page renders hardcoded HTML from the `DOC_CONTENT` and `DOC_DISC_CONTENT` objects in `js/pages/docs.js`. This is the user-facing documentation that visitors see on the website, distinct from the repo-level markdown files.

When to add a new article:
- A major new feature was added that users need to learn (e.g., skill installation, discussion zone, browser extension)
- An existing article references a concept that doesn't have its own article yet
- The feature has a multi-step workflow users need guidance on

How to add:
1. Add a new entry to `DOC_CONTENT` with `title`, `icon` (Unicode emoji), `time` (read estimate), and `body` (HTML string)
2. Add a matching entry to the `SLUGS` object: `'Article Title': 'url-slug'`
3. The article is automatically rendered in the grid on `#docs` and navigable at `#docs/slug`

Style rules for article HTML:
- Use `<h2>` for the main heading, `<h3>` for sub-sections
- Use `<ul>/<ol>` for lists, `<strong>` for emphasis
- Code blocks: `<div style="padding:.8rem;background:var(--bg-raised);border-radius:8px;font-family:var(--f-mono);font-size:.78rem;margin:1rem 0;line-height:1.7;color:var(--text-dim);white-space:pre;overflow-x:auto;">...</div>`
- Internal links: `<a href="#tools">Tools</a>` (hash-based SPA routes)
- Keep body text concise — aim for 5-8 min read time

What to check on existing articles:
- Do they reference features that have changed? (e.g., "Coming soon" for features now live)
- Are example commands and API endpoints still correct?
- Does the article count in README match actual `Object.keys(DOC_CONTENT).length + Object.keys(DOC_DISC_CONTENT).length`?

Current article inventory (audit this):
- Core concepts: getting-started, what-is-a-skill, what-is-an-agent, reading-a-trace, uploading-datasets, agent-integration, installing-skills, building-pipelines
- Discipline guides: combustion, physics, math, biology, ai, materials

### Step 4 — Verify accuracy

After updates, spot-check:
- Do file counts match `ls` output?
- Are all directories in structure trees real?
- Do test commands actually work?
- Are new features mentioned in at least 2 docs (README + CLAUDE)?

### Step 5 — Commit

```bash
git add README.md CLAUDE.md STYLE.md docs/DEPLOY.md trace.md js/pages/docs.js
git commit -m "docs: sync all documentation with current codebase state"
```

## Key Principles

1. **Accuracy over completeness** — better to omit a detail than state it incorrectly
2. **Cross-reference** — major features should appear in both README.md and CLAUDE.md
3. **Concrete numbers** — "14 page files" not "page renderers", "92 tests" not "comprehensive tests"
4. **Maintenance burden** — don't document things that change frequently (e.g., exact line counts)
5. **Audience-specific** — README for users/contributors, CLAUDE.md for AI agents, STYLE.md for designers/frontend devs

## Common Pitfalls

- **Forgetting to update both README and CLAUDE** — they have overlapping structure trees
- **Stale file counts** — always verify with `ls` before updating
- **Missing test docs** — testing is critical but often undocumented
- **Deployment drift** — setup.sh changes don't make it into DEPLOY.md
- **STYLE.md neglect** — new UI components added without design system guidance
- **Web docs page forgotten** — `js/pages/docs.js` has hardcoded articles that drift from reality. New features need new articles, and existing articles may reference stale APIs or "Coming soon" features that are now live
