# gaia-discovery API Reference

## Core Functions

### run_discovery()
```python
from dz_engine import run_discovery, MCTSConfig
from pathlib import Path

result = run_discovery(
    graph_path=Path("conjecture.json"),
    target_node_id="conjecture_1",
    config=MCTSConfig(...),
    model="gpt-4o",
)
```

Runs MCTS discovery on target conjecture.

Returns `DiscoveryResult` with:
- `iterations_completed`: int
- `target_belief_initial`: float
- `target_belief_final`: float
- `success`: bool
- `elapsed_ms`: int
- `best_bridge_plan`: Optional[BridgePlan]
- `best_bridge_confidence`: float
- `traces`: List[IterationTrace]
- `graph`: HyperGraph (final state)

### MCTSDiscoveryEngine
```python
from dz_engine import MCTSDiscoveryEngine

engine = MCTSDiscoveryEngine(
    graph_path=Path("conjecture.json"),
    target_node_id="target",
    config=MCTSConfig(...),
    model="gpt-4o",
    backend="bp",
    bridge_path=Path("bridge-plan.json"),
    llm_record_dir=Path("llm_records"),
    # Optional: custom engines
    analogy_engine=custom_analogy,
)

result = engine.run()
```

## Data Models

### MCTSConfig
```python
@dataclass
class MCTSConfig:
    max_iterations: int = 50
    max_time_seconds: int = 14400  # 4 hours
    c_puct: float = 1.4            # UCB exploration coefficient
    enable_evolutionary_experiments: bool = True
    enable_continuation_verification: bool = True
    enable_retrieval: bool = False
    enable_problem_variants: bool = False
```

### DiscoveryResult
```python
@dataclass
class DiscoveryResult:
    iterations_completed: int
    target_belief_initial: float
    target_belief_final: float
    success: bool
    elapsed_ms: int
    best_bridge_plan: Optional[BridgePlan]
    best_bridge_confidence: float
    traces: List[IterationTrace]
    graph: HyperGraph
```

### IterationTrace
```python
@dataclass
class IterationTrace:
    iteration: int
    module: str              # "ANALOGY", "DECOMPOSE", etc.
    target_belief_before: float
    target_belief_after: float
    reward: float
```

### BridgePlan
```python
@dataclass
class BridgePlan:
    propositions: List[Proposition]
    confidence: float
```

## Exploration Modules

### AnalogyEngine
```python
from dz_engine.analogy import AnalogyEngine

engine = AnalogyEngine()
engine.domain_knowledge = load_kb("domain.json")
```

### DecomposeEngine
```python
from dz_engine.decompose import DecomposeEngine

engine = DecomposeEngine()
```

### SpecializeEngine
```python
from dz_engine.specialize import SpecializeEngine

engine = SpecializeEngine()
```

## Configuration

### MCTS Settings
```bash
DISCOVERY_ZERO_MCTS_MAX_ITERATIONS=50
DISCOVERY_ZERO_MCTS_MAX_TIME_SECONDS=14400
DISCOVERY_ZERO_MCTS_C_PUCT=1.4
```

### Module Toggles
```bash
DISCOVERY_ZERO_ENABLE_CLAIM_VERIFIER=true
DISCOVERY_ZERO_ENABLE_ANALOGY=true
DISCOVERY_ZERO_ENABLE_DECOMPOSE=true
```

### Retrieval (Optional)
```bash
EMBEDDING_API_BASE=https://your-embedding-api.example.com
```

## Usage Pattern

```python
from pathlib import Path
from dz_hypergraph import create_graph, save_graph
from dz_hypergraph.models import Node
from dz_engine import run_discovery, MCTSConfig

# 1. Create graph with target
graph = create_graph()
target = Node(
    id="target",
    statement="Your conjecture here",
    state="unverified",
    belief=0.3,
    prior=0.3,
)
graph.nodes[target.id] = target
save_graph(graph, Path("input.json"))

# 2. Run discovery
result = run_discovery(
    graph_path=Path("input.json"),
    target_node_id="target",
    config=MCTSConfig(max_iterations=20),
    model="gpt-4o",
)

# 3. Analyze results
print(f"Belief: {result.target_belief_initial:.3f} -> {result.target_belief_final:.3f}")
if result.best_bridge_plan:
    for step in result.best_bridge_plan.propositions:
        print(f"  -> {step.statement}")

# 4. Save final graph
save_graph(result.graph, Path("output.json"))
```
