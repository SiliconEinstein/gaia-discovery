---
name: gaia-discovery
description: "MCTS scientific discovery engine for iterative exploration of conjectures. Use when: (1) running MCTS search on scientific hypotheses, (2) generating Bridge plans for multi-step reasoning, (3) exploring via analogy, decomposition, specialization, (4) evolving experiments through mutation and retry, (5) collecting expert iteration data. NOT for: hypergraph management (use gaia-hypergraph), claim verification (use gaia-verify), or MCP access (use gaia-mcp-bridge)."
---

# gaia-discovery

MCTS scientific discovery engine for iterative exploration of conjectures.
Part of the gaia-discovery ecosystem.

## When to Use

✅ **USE this skill when:**
- Running MCTS search on scientific hypotheses
- Generating Bridge plans for multi-step reasoning
- Exploring via analogy, decomposition, specialization
- Evolving experiments through mutation and retry
- Collecting expert iteration data for offline RL

❌ **DON'T use this skill when:**
- Managing hypergraphs → use **gaia-hypergraph**
- Verifying claims → use **gaia-verify**
- Needing MCP access → use **gaia-mcp-bridge**

## Prerequisites

### Required
- Python >= 3.12
- gaia-hypergraph skill (dependency)
- gaia-verify skill (dependency)
- Gaia DSL Runtime: `pip install -e /path/to/Gaia`

### Environment Variables
```bash
# LLM Configuration (required)
LITELLM_PROXY_API_BASE=https://your-llm-proxy.example.com/v1
LITELLM_PROXY_API_KEY=sk-your-key-here
LITELLM_PROXY_MODEL=gpt-4o

# MCTS Configuration
DISCOVERY_ZERO_MCTS_MAX_ITERATIONS=50        # max iterations
DISCOVERY_ZERO_MCTS_MAX_TIME_SECONDS=14400   # max time (4 hours)
DISCOVERY_ZERO_MCTS_C_PUCT=1.4               # UCB exploration coefficient

# Module Toggles
DISCOVERY_ZERO_ENABLE_CLAIM_VERIFIER=true    # enable verification
DISCOVERY_ZERO_ENABLE_ANALOGY=true           # enable analogy
DISCOVERY_ZERO_ENABLE_DECOMPOSE=true         # enable decomposition
```

## Core Concepts

### MCTS (Monte Carlo Tree Search)
- **Selection**: UCB-based node selection
- **Expansion**: Progressive widening
- **Simulation**: Bridge plan execution
- **Backpropagation**: Belief update via BP

### Bridge Planning
LLM-generated multi-step reasoning plans with structured validation.

### Exploration Modules

| Module | Function |
|--------|----------|
| AnalogyEngine | Cross-domain analogical reasoning |
| DecomposeEngine | Problem decomposition into subgoals |
| SpecializeEngine | Problem specialization/generalization |
| KnowledgeRetriever | Knowledge retrieval and injection |

## Usage

### Basic Discovery
```python
from pathlib import Path
from dz_hypergraph import create_graph, save_graph
from dz_hypergraph.models import Node
from dz_engine import run_discovery, MCTSConfig

# 1. Build initial hypergraph with target conjecture
graph = create_graph()
target = Node(
    id="conjecture_1",
    statement="For all n >= 3, there exist n consecutive composite numbers",
    state="unverified",
    belief=0.3,
    prior=0.3,
    domain="number_theory",
)
graph.nodes[target.id] = target

# Add known seeds
axiom = Node(
    id="axiom_factorial",
    statement="n! is the product of all integers from 1 to n",
    state="proven",
    belief=1.0,
    prior=1.0,
)
graph.nodes[axiom.id] = axiom

save_graph(graph, Path("conjecture.json"))

# 2. Run MCTS discovery
result = run_discovery(
    graph_path=Path("conjecture.json"),
    target_node_id="conjecture_1",
    config=MCTSConfig(
        max_iterations=20,
        max_time_seconds=1800,
        c_puct=1.4,
        enable_evolutionary_experiments=True,
        enable_continuation_verification=True,
        enable_retrieval=False,  # requires EMBEDDING_API_BASE
        enable_problem_variants=False,
    ),
    model="gpt-4o",
)

# 3. Check results
print(f"Iterations: {result.iterations_completed}")
print(f"Belief: {result.target_belief_initial:.3f} -> {result.target_belief_final:.3f}")
print(f"Success: {result.success}")
```

### Advanced Configuration
```python
from dz_engine import MCTSConfig

config = MCTSConfig(
    max_iterations=30,
    max_time_seconds=3600,
    c_puct=1.4,
    enable_evolutionary_experiments=True,   # mutate failed experiments
    enable_continuation_verification=True,  # continuous verification
    enable_retrieval=False,                  # knowledge retrieval
    enable_problem_variants=False,           # problem specialization
)
```

### Custom Engines
```python
from dz_engine.analogy import AnalogyEngine
from dz_engine import MCTSDiscoveryEngine

# Custom analogy engine
custom_analogy = AnalogyEngine()
custom_analogy.domain_knowledge = load_domain_kb("physics.json")

engine = MCTSDiscoveryEngine(
    graph_path=Path("conjecture.json"),
    target_node_id="target",
    config=config,
    model="gpt-4o",
    analogy_engine=custom_analogy,  # override default
)

result = engine.run()
```

## Result Analysis

### Best Bridge Plan
```python
if result.best_bridge_plan:
    print(f"Best plan (confidence {result.best_bridge_confidence:.3f}):")
    for step in result.best_bridge_plan.propositions:
        print(f"  -> {step.statement}")
```

### Iteration Traces
```python
for trace in result.traces:
    print(f"Iter {trace.iteration}: [{trace.module}] "
          f"belief {trace.target_belief_before:.3f}->{trace.target_belief_after:.3f} "
          f"(reward={trace.reward:.3f})")
```

### Final Graph
```python
from dz_hypergraph import save_graph
save_graph(result.graph, Path("final_graph.json"))
```

## Architecture

```
MCTS Loop
    │
    ▼ Selection (UCB)
Selected Node
    │
    ▼ Expansion (Progressive Widening)
New Node
    │
    ▼ Bridge Planning
Bridge Plan
    │
    ▼ Module Selection
├─▶ Analogy
├─▶ Decomposition
├─▶ Specialization
├─▶ Experiment
└─▶ Retrieval
    │
    ▼ Execution
├─▶ gaia-verify (claim verification)
└─▶ gaia-hypergraph (BP propagation)
    │
    ▼ Backpropagation
Updated Beliefs
```

## HTPS Path Selection

Graph-aware leaf node selection prioritizing high information gain paths.

## Expert Iteration

Collect experience records for offline RL training:
```python
# Experience records automatically collected in result.traces
# Format: (state, action, reward, next_state)
```

## Scripts

- `scripts/validate.py` - Run validation tests

## References

- `references/api.md` - Complete API documentation
- `references/mcts.md` - MCTS algorithm details
- `references/modules.md` - Exploration modules guide

## Dependencies

- gaia-hypergraph (dependency)
- gaia-verify (dependency)
- gaia-lang (SiliconEinstein/Gaia)
- dz-engine package (from gaia-discovery)

## Related Skills

- **gaia-hypergraph** - Hypergraph management and BP
- **gaia-verify** - Claim extraction and verification
- **gaia-mcp-bridge** - MCP server bridge

## Performance Notes

- MCTS can run for hours depending on configuration
- Set `max_time_seconds` to limit runtime
- Enable/disable modules based on problem needs
- Retrieval requires `EMBEDDING_API_BASE` configuration
