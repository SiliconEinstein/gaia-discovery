# gaia-hypergraph Data Models

**Source**: These are DZ (Discovery-Zero) data models that interface with [SiliconEinstein/Gaia](https://github.com/SiliconEinstein/Gaia).

**Key Point**: The actual hypergraph storage, Gaia IR, and BP engine are **in Gaia**, not here.
This skill provides the DZ-layer data models and bridge functions.

## HyperGraph

The DZ-layer data structure containing nodes and edges.
Bridged to Gaia IR via `bridge_to_gaia()`.

```python
class HyperGraph:
    nodes: Dict[str, Node]
    edges: Dict[str, Hyperedge]
```

## Node

Represents a proposition in the reasoning graph.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| id | str | Unique identifier (auto-generated) |
| statement | str | Natural language proposition |
| formal_statement | Optional[str] | Lean formalization |
| belief | float | Posterior belief [0,1], updated by BP |
| prior | float | Prior belief [0,1], BP input |
| state | str | "unverified" \| "proven" \| "refuted" |
| domain | Optional[str] | Domain tag (e.g., "number_theory") |
| provenance | Optional[str] | Source marker |
| verification_source | Optional[str] | "experiment" \| "lean" \| "llm_judge" |
| memo_ref | Optional[str] | Associated ResearchMemo ID |

### Belief Semantics

- **belief**: BP posterior confidence, updated by **Gaia BP engine** (`gaia.bp.engine.InferenceEngine`)
- **prior**: Prior confidence, set by verification results or manually, BP input
- **state="proven"**: prior=1.0, belief=1.0 (locked, BP won't modify)
- **state="refuted"**: prior=0.0, belief=0.0 (locked, BP won't modify)

**Note**: BP is performed by Gaia, not by this skill. This skill only stores the results.

## Hyperedge

Represents a reasoning step connecting premises to conclusion.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| id | str | Unique identifier |
| premise_ids | List[str] | IDs of premise nodes |
| conclusion_id | str | ID of conclusion node |
| module | Module | Originating module |
| steps | List[str] | Reasoning step descriptions |
| confidence | float | Edge confidence [0,1] |
| edge_type | str | "heuristic" \| "formal" \| "decomposition" |

### Module Types

| Module | Description |
|--------|-------------|
| PLAUSIBLE | Plausible reasoning |
| EXPERIMENT | Experimental verification |
| LEAN | Lean formal proof |
| ANALOGY | Analogical reasoning |
| DECOMPOSE | Problem decomposition |
| SPECIALIZE | Problem specialization |
| RETRIEVE | Knowledge retrieval |

### Edge Type Mapping to Gaia IR

| edge_type | Gaia Strategy | Description |
|-----------|---------------|-------------|
| "heuristic" | type="infer" | Plausible inference |
| "formal" | type="deduction" | Deductive reasoning |
| "decomposition" | type="infer" | Problem decomposition |

## BridgeResult

Result of `bridge_to_gaia()` compilation.

```python
@dataclass
class BridgeResult:
    compiled: CompiledResult          # Contains LocalCanonicalGraph
    node_priors: Dict[str, float]     # {qid: prior_value}
    strategy_params: Dict[str, List]  # {strategy_id: [cpt]}
    dz_id_to_qid: Dict[str, str]      # DZ node ID → Gaia QID
    prior_records: List[PriorRecord]
    strategy_param_records: List[StrategyParamRecord]
```

## CompiledResult

```python
@dataclass
class CompiledResult:
    graph: LocalCanonicalGraph  # Gaia IR with ir_hash
```

## Serialization Format

### Graph JSON Structure

```json
{
  "nodes": {
    "node_id": {
      "id": "node_id",
      "statement": "...",
      "belief": 0.5,
      "prior": 0.5,
      "state": "unverified",
      ...
    }
  },
  "edges": {
    "edge_id": {
      "id": "edge_id",
      "premise_ids": ["node_a", "node_b"],
      "conclusion_id": "node_c",
      "module": "PLAUSIBLE",
      "steps": ["..."],
      "confidence": 0.7,
      "edge_type": "heuristic"
    }
  }
}
```

## Gaia Artifacts Output

### Directory Structure

```
output/
└── .gaia/
    ├── ir.json                    # LocalCanonicalGraph
    ├── ir_hash                    # sha256 hash
    └── reviews/
        └── dz_bridge/
            ├── parameterization.json   # PriorRecord + StrategyParamRecord
            └── beliefs.json            # Belief snapshot
```

### ir.json

Standard Gaia IR format with:
- QID assignments
- Strategy definitions
- Constraint definitions
- ir_hash for verification

### parameterization.json

Contains prior and strategy parameter records for Gaia validation.

### beliefs.json

Belief snapshot compatible with `gaia infer` output schema.
