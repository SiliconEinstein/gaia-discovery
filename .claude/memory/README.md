# .claude/memory/ — Structured Knowledge Base
#
# This directory contains curated, git-tracked knowledge accumulated
# across development sessions. It is NOT a log — each entry must be
# actionable, specific, and dated.
#
# Files:
#   pitfalls.yaml      — Bugs found and how to avoid them
#   patterns.yaml      — Confirmed workflows and checklists
#   decisions.yaml     — Architectural choices with rationale
#   review-insights.yaml — Valuable feedback from external reviews
#
# Rules:
#   - Max 50 entries per file (archive older entries if needed)
#   - Each entry has: id, date, title, and domain-specific fields
#   - When a pitfall can be automated, promote it to check_invariants.py
#   - YAML format for both human and machine readability
#   - Git history IS the evolution timeline (use git log/diff/blame)
