---
name: orchestrate
description: "Enter orchestrator mode: coordinate multiple Claude Code sessions as workers. Use this when you want to run parallel workstreams, delegate tasks to worker sessions, or manage a team of agents. The orchestrator maintains strategic context while workers execute specific tasks. Usage: /orchestrate [plan|status|spawn|recall|kill]"
version: 2.0.0
author: tianhanz
tags: [multi-agent, coordination, session-management, parallel-execution]
---

# Orchestrate Skill

Coordinate multiple Claude Code sessions as an orchestrator. The orchestrator
maintains strategic context and decision-making authority while spawning worker
sessions to execute specific tasks in parallel.

**Arguments:** $ARGUMENTS

## Concepts

- **Orchestrator**: The main session (you) that maintains the big picture, makes
  decisions, and coordinates workers. Thinks like tianhanz — strategic, decisive,
  delegates execution but owns the judgment calls.

- **Worker**: A spawned Claude Code session that executes a specific task. Workers
  write their progress and decisions to `.claude/state/session-<id>.yaml`. When
  done, they mark status=completed with structured results.

- **Session State**: Structured YAML files in `.claude/state/` that enable cross-session
  coordination. Each session writes its own state; the orchestrator reads all states.
  All writes are protected by file locking (fcntl) — safe for concurrent access.

- **Failure Taxonomy**: Workers report outcomes using a 5-category system:
  `success` (task completed), `blocked` (waiting on external input/decision),
  `env_failure` (tooling/infra issue), `timeout` (exceeded time limit),
  `inconclusive` (unclear if done, needs human review).

## Subcommands

### /orchestrate plan

Plan the work breakdown and identify parallelizable tasks.

1. Ask: "What's the overall goal? What are the major workstreams?"
2. Identify tasks that can run in parallel (independent) vs sequential (dependent)
3. For each parallelizable task, draft a worker prompt
4. Output a dependency graph:

```yaml
# Work plan with dependencies
tasks:
  - id: task-1
    description: "Review OTM radiation"
    dependencies: []        # Can start immediately
    estimated_complexity: low
    worker_type: review      # review | implement | test | research

  - id: task-2
    description: "Review SNB radiation"
    dependencies: []         # Can run in parallel with task-1
    estimated_complexity: medium
    worker_type: review

  - id: task-3
    description: "Fix issues found in review"
    dependencies: [task-1, task-2]  # Blocked until reviews complete
    estimated_complexity: high
    worker_type: implement
```

**Dependency-aware scheduling**: When spawning workers, check that all
dependencies are satisfied (predecessor tasks have outcome=success). If a
predecessor failed, propagate the failure — don't spawn blocked tasks.

### /orchestrate status

Check status of all active sessions.

```bash
echo "=== Active Sessions ==="
for f in .claude/state/session-*.yaml .claude/state/current.yaml; do
  [ -f "$f" ] || continue
  echo "--- $(basename "$f") ---"
  python3 -c "
import yaml
with open('$f') as fh:
    s = yaml.safe_load(fh)
print(f\"  Session:   {s.get('session_id', '?')}\")
print(f\"  Role:      {s.get('role', '?')}\")
print(f\"  Status:    {s.get('status', '?')}\")
print(f\"  Task:      {s.get('current_task', '(none)')}\")
print(f\"  Heartbeat: {s.get('last_heartbeat', '?')}\")
print(f\"  Decisions: {len(s.get('decisions', []))}\")
print(f\"  Artifacts: {len(s.get('artifacts', []))}\")
result = s.get('result', {})
if result:
    print(f\"  Outcome:   {result.get('outcome', '?')}\")
    print(f\"  Summary:   {result.get('summary', '?')[:60]}\")
# Check provenance
prov = s.get('provenance', {})
if prov:
    print(f\"  Solver:    {prov.get('solver', '?')} {prov.get('solver_version', '')}\")
    print(f\"  Mechanism: {prov.get('mechanism', '?')}\")
# Heartbeat staleness warning
import datetime
hb = s.get('last_heartbeat', '')
if hb and s.get('status') == 'active':
    try:
        from datetime import datetime as dt, timezone
        last = dt.fromisoformat(hb.replace('Z', '+00:00'))
        age = (dt.now(timezone.utc) - last).total_seconds()
        if age > 600:  # 10 min stale
            print(f\"  ⚠ STALE: no heartbeat for {int(age)}s\")
    except: pass
"
done
```

Also check `.claude/state/archive/` for recently completed sessions.

**Stale session detection**: If a worker's heartbeat is >10 minutes old and
status is still `active`, it may have crashed. Options:
1. Check the log file for errors
2. Use `/orchestrate kill <session-id>` to clean up
3. Retry the task with a new worker

### /orchestrate spawn <task-description>

Spawn a new worker session to execute a specific task.

1. **Check dependencies**: Verify all prerequisite tasks are complete (outcome=success).
   If any predecessor has outcome=blocked|env_failure|timeout|inconclusive, stop
   and report the blocking issue.

2. Generate a worker prompt that includes:
   - The specific task to accomplish
   - Success criteria (how to know when done)
   - Expected artifacts (files to produce)
   - Failure conditions (when to stop and report blocked/env_failure)
   - Scientific provenance context (solver, mechanism if applicable)
   - Instruction to use `ears-state` for state management

3. Launch the worker in background:
   ```bash
   # Generate session ID
   WORKER_ID="worker-$(date +%s)-$(head -c 4 /dev/urandom | xxd -p)"

   # Create logs directory
   mkdir -p .claude/state/logs

   # Create initial state file with provenance
   python3 ~/.local/bin/ears-state init \
     --role worker \
     --parent <orchestrator-id> \
     --solver <solver-name> \
     --mechanism <mechanism-file>

   # Launch worker (non-blocking)
   nohup claude -p "<worker-prompt>" \
     --allowedTools Edit,Read,Write,Grep,Glob,Bash \
     > .claude/state/logs/${WORKER_ID}.log 2>&1 &

   WORKER_PID=$!
   echo "Spawned worker: $WORKER_ID (PID: $WORKER_PID)"

   # Record PID in state for kill support
   python3 -c "
   import yaml
   sf = '.claude/state/current.yaml'
   with open(sf) as f:
       state = yaml.safe_load(f)
   state['pid'] = $WORKER_PID
   with open(sf, 'w') as f:
       yaml.dump(state, f, default_flow_style=False)
   "
   ```

4. Record the worker in orchestrator's children list

**Worker prompt template** (include in every worker prompt):
```
You are a worker session. Your task: <TASK>

State management:
- Run: ears-state task "<one-line description>"
- For each decision: ears-state decision --type <type> --summary "<what>"
- For each output file: ears-state artifact --path <path> --role output
- When done: ears-state end --summary "<what you did>" --outcome <success|blocked|env_failure>
- If blocked: ears-state end --outcome blocked --summary "Blocked on: <what>"
- If environment issue: ears-state end --outcome env_failure --summary "Failed: <why>"

Scientific provenance:
- Solver: <solver> v<version>
- Mechanism: <mechanism file>
- Record any parameter choices with: ears-state decision --type parameter_selection

Success criteria: <CRITERIA>
Expected artifacts: <FILES>

When you complete your task or encounter and fix an error, append a brief
entry to the nearest trace.md. Format: `### EARS — <type> (date)` followed
by `<!-- concepts: area1, area2 -->` with what happened, root cause, and
lesson. Skip if nothing notable.
```

### /orchestrate recall

Review completed workers and integrate their results.

1. Scan `.claude/state/archive/` for completed sessions with parent = current orchestrator
2. For each completed worker:
   - Read its decisions array
   - Read its result (outcome + summary + findings)
   - Check artifact existence (verify output files exist on disk)
   - Integrate key decisions into orchestrator's state
3. **Outcome-aware processing**:
   - `success` → integrate results, mark task done
   - `blocked` → escalate blocker to orchestrator, decide whether to retry or ask user
   - `env_failure` → check if environment issue is transient (retry) or persistent (escalate)
   - `timeout` → check partial results, decide whether to spawn continuation or retry
   - `inconclusive` → review findings, make judgment call
4. Update orchestrator's view of what's been accomplished
5. Check if newly completed tasks unblock downstream dependencies

### /orchestrate kill <session-id>

Terminate a worker session that is stale, stuck, or no longer needed.

```bash
python3 ~/.local/bin/ears-state kill <session-id> --reason "<reason>"
```

This will:
1. Send SIGTERM to the worker process (if PID recorded)
2. Mark the session as failed with outcome=timeout
3. Archive the session state

## Workflow Example

```
User: "Review all radiation models in pyASURF"

/orchestrate plan
→ Identified 3 tasks with dependencies:
  task-1: Review OTM implementation (deps: none)
  task-2: Review SNB implementation (deps: none)
  task-3: Fix issues found in review (deps: task-1, task-2)

/orchestrate spawn "Dispatch action_id=A1 (deduction route) on claim_qid=sqrt2.irr.c01."
→ Spawned worker-1744567890-a3f2 (PID: 12345)
  Provenance: backend=claude router=structural

/orchestrate spawn "Dispatch action_id=A2 (heuristic support) on claim_qid=sqrt2.irr.c02."
→ Spawned worker-1744567891-b4c3 (PID: 12346)
  Provenance: backend=claude router=heuristic

/orchestrate status
→ worker-1: active, dispatching A1 (structural) (heartbeat 30s ago)
→ worker-2: active, dispatching A2 (heuristic) (heartbeat 45s ago)

[... workers complete ...]

/orchestrate recall
→ worker-1: outcome=success
   Found: verified=true, evidence premise_qids=[nat.prime.defn, euclid.lemma]
   Artifacts: [trace.md updated]
→ worker-2: outcome=success
   Found: inconclusive(insufficient_evidence), single judge + 1 premise
   Artifacts: [trace.md updated]
→ Integrated 4 decisions into orchestrator state
→ task-3 unblocked: all dependencies (task-1, task-2) succeeded

/orchestrate spawn "Spawn A2b with 2+ independent premises per Oracle recommendation..."
→ Spawned worker-1744567900-c5d4 (PID: 12347)
```

## State Files

**Orchestrator state**: `.claude/state/current.yaml`
```yaml
schema_version: '2.0'
session_id: orch-1744567800-xyz
role: orchestrator
status: active
provenance:
  backend: claude
  backend_version: 2.1.123
children:
  - worker-1744567890-a3f2
  - worker-1744567891-b4c3
decisions:
  - type: scope_change
    summary: "Split iter_03 dispatch into 3 parallel action_id workers"
```

**Worker state (completed)**: `.claude/state/archive/worker-xxx.yaml`
```yaml
schema_version: '2.0'
session_id: worker-1744567890-a3f2
role: worker
parent_session: orch-1744567800-xyz
status: completed
provenance:
  backend: claude
  backend_version: 2.1.123
current_task: "Dispatch A1 structural on sqrt2.irr.c01"
decisions:
  - type: design_choice
    summary: "verdict=verified; premise_qids closed under graph"
artifacts:
  - path: projects/sqrt2_irrational/iter_03/plan.gaia.py
    role: input
  - path: trace.md
    role: output
    decision_ref: 0
result:
  outcome: success
  summary: "Verified 1 claim: sqrt2.irr.c01"
  findings:
    verdicts_emitted: 1
    strength: 0.86
    files_affected: ["runs/r0301/verification.json"]
```

**Worker state (failed)**: `.claude/state/archive/worker-yyy.yaml`
```yaml
schema_version: '2.0'
session_id: worker-1744567891-b4c3
role: worker
parent_session: orch-1744567800-xyz
status: failed
result:
  outcome: env_failure
  summary: "claude CLI exited non-zero — MAX_OUTPUT_TOKENS=0 bug"
  reason: "W8 stream-json parser crash on GPT-5.4 output — retry with --model Vendor2/Claude-4.5-Sonnet"
```

## Notes

- **File locking**: All state writes use `fcntl.flock` with 5s timeout. Safe for
  concurrent orchestrator + multiple workers writing simultaneously.
- **Atomic writes**: State files are written via temp file + rename, preventing
  partial reads during concurrent access.
- **Workers are full Claude Code sessions** with EARS hooks, so their decisions
  automatically get captured in structured state.
- The orchestrator doesn't need to poll — check status when you want to make
  a decision or when enough time has passed.
- Workers should be given clear, bounded tasks. "Review this file" is good.
  "Refactor everything" is too broad.
- If a worker gets stuck, you can read its state and intervene with guidance.
- **Stale detection**: Workers with >10 min heartbeat gap may have crashed.
  Use `/orchestrate kill` to clean up before retrying.
- **Dependency scheduling**: Never spawn a task whose dependencies haven't
  all completed successfully. Propagate failures upward.
