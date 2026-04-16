# gaia-hypergraph API Reference

**Note**: These are wrapper functions. Core BP and inference logic is in [SiliconEinstein/Gaia](https://github.com/SiliconEinstein/Gaia).

## Core Functions

### create_graph()
```python
from dz_hypergraph import create_graph

graph = create_graph()
```
Creates empty HyperGraph instance.

### save_graph()
```python
from dz_hypergraph import save_graph
from pathlib import Path

save_graph(graph, Path("output.json"))
```
Serializes graph to JSON file.

### load_graph()
```python
from dz_hypergraph import load_graph

graph = load_graph("output.json")
```
Loads graph from JSON file.

### bridge_to_gaia()
```python
from dz_hypergraph import bridge_to_gaia

result = bridge_to_gaia(graph)
```
Compiles DZ hypergraph to Gaia IR.

Returns `BridgeResult` with:
- `compiled.graph`: LocalCanonicalGraph
- `compiled.graph.ir_hash`: sha256 hash
- `node_priors`: {qid: float}
- `strategy_params`: {strategy_id: [cpt]}
- `dz_id_to_qid`: DZ node ID → Gaia QID mapping

### save_gaia_artifacts()
```python
from dz_hypergraph import save_gaia_artifacts
from pathlib import Path

save_gaia_artifacts(graph, Path("output/"))
```
Exports standard Gaia artifacts to `.gaia/` directory.

### propagate_beliefs()
```python
from dz_hypergraph import propagate_beliefs

iterations = propagate_beliefs(graph)
```
Runs BP until convergence using `gaia.bp.engine.InferenceEngine`. Returns iteration count.

### analyze_belief_gaps()
```python
from dz_hypergraph import analyze_belief_gaps

gaps = analyze_belief_gaps(graph, target_node_id="node_id", top_k=5)
```
Returns list of (node_id, information_gain) tuples sorted by gain.

## Data Models

### Node
```python
@dataclass
class Node:
    id: str
    statement: str
    formal_statement: Optional[str] = None
    belief: float = 0.5
    prior: float = 0.5
    state: str = "unverified"  # "unverified" | "proven" | "refuted"
    domain: Optional[str] = None
    provenance: Optional[str] = None
    verification_source: Optional[str] = None
    memo_ref: Optional[str] = None
```

### Hyperedge
```python
@dataclass
class Hyperedge:
    id: str
    premise_ids: List[str]
    conclusion_id: str
    module: Module
    steps: List[str]
    confidence: float
    edge_type: str  # "heuristic" | "formal" | "decomposition"
```

### Module (Enum)
- PLAUSIBLE
- EXPERIMENT
- LEAN
- ANALOGY
- DECOMPOSE
- SPECIALIZE
- RETRIEVE

## Configuration

All via environment variables with `DISCOVERY_ZERO_` prefix:

### BP Settings
- `DISCOVERY_ZERO_BP_BACKEND`: gaia_v2 or energy
- `DISCOVERY_ZERO_BP_MAX_ITERATIONS`: int (default: 50)
- `DISCOVERY_ZERO_BP_DAMPING`: float (default: 0.5)
- `DISCOVERY_ZERO_BP_TOLERANCE`: float (default: 1e-6)
- `DISCOVERY_ZERO_BP_INCREMENTAL`: bool (default: true)
- `DISCOVERY_ZERO_INFERENCE_METHOD`: auto/jt/gbp/loopy

### Node Defaults
- `DISCOVERY_ZERO_UNVERIFIED_CLAIM_PRIOR`: float (default: 0.5)
- `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_PLAUSIBLE`: float (default: 0.5)
- `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_EXPERIMENT`: float (default: 0.85)
- `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_LEAN`: float (default: 0.99)
