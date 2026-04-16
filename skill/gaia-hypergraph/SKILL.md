---
name: gaia-hypergraph
description: "Hypergraph data model and Bayesian Belief Propagation for scientific reasoning. Use when: (1) creating and managing reasoning hypergraphs with Node/Hyperedge structures, (2) compiling DZ hypergraphs to Gaia IR via bridge_to_gaia(), (3) running belief propagation with Gaia BP engine, (4) analyzing belief gaps in reasoning chains, (5) exporting to standard Gaia artifacts. NOT for: claim verification (use gaia-verify), MCTS discovery (use gaia-discovery), or MCP server access (use gaia-mcp-bridge)."
---

# gaia-hypergraph

Hypergraph data model and Bayesian Belief Propagation for scientific reasoning.
Part of the gaia-discovery ecosystem.

**Key Point**: This skill is a **wrapper and bridge** to [SiliconEinstein/Gaia](https://github.com/SiliconEinstein/Gaia).
All core hypergraph logic, Gaia IR compilation, and Belief Propagation are **fully reused** from the Gaia repository.
This skill does NOT reimplement any BP or inference logic — it delegates 100% to Gaia components.

## When to Use

✅ **USE this skill when:**
- Creating reasoning hypergraphs with Node/Hyperedge structures
- Compiling DZ hypergraphs to Gaia IR via `bridge_to_gaia()`
- Running belief propagation with Gaia BP engine
- Analyzing belief gaps in reasoning chains
- Exporting to standard Gaia artifacts (.gaia/ directory)

❌ **DON'T use this skill when:**
- Extracting and verifying claims from text → use **gaia-verify**
- Running MCTS discovery on conjectures → use **gaia-discovery**
- Needing MCP server access → use **gaia-mcp-bridge**

## Prerequisites

### Required
- Python >= 3.12
- Gaia DSL Runtime: `pip install -e /path/to/Gaia`

### Environment Variables
```bash
# LLM Configuration (required for some operations)
LITELLM_PROXY_API_BASE=https://your-llm-proxy.example.com/v1
LITELLM_PROXY_API_KEY=sk-your-key-here
LITELLM_PROXY_MODEL=gpt-4o

# BP Configuration
DISCOVERY_ZERO_BP_BACKEND=gaia_v2        # gaia_v2 or energy
DISCOVERY_ZERO_BP_MAX_ITERATIONS=50      # max BP iterations
DISCOVERY_ZERO_BP_DAMPING=0.5            # damping factor
DISCOVERY_ZERO_BP_TOLERANCE=1e-6         # convergence tolerance
DISCOVERY_ZERO_BP_INCREMENTAL=true       # incremental BP
DISCOVERY_ZERO_INFERENCE_METHOD=auto     # auto/jt/gbp/loopy
```

## Core Concepts

### Node (Proposition)
```python
Node(
    id="auto_generated",              # unique ID
    statement="命题的自然语言描述",      # required
    formal_statement=None,            # optional: Lean formalization
    belief=0.5,                       # posterior belief [0,1] (BP updated)
    prior=0.5,                        # prior belief [0,1] (BP input)
    state="unverified",               # "unverified" | "proven" | "refuted"
    domain=None,                      # domain tag
    provenance=None,                  # source marker
    verification_source=None,         # "experiment" | "lean" | "llm_judge"
    memo_ref=None,                    # ResearchMemo ID
)
```

**Belief semantics:**
- `belief` = BP posterior (updated by propagation)
- `prior` = prior from verification or manual setting (BP input)
- `state="proven"` → prior=1.0, belief=1.0 (locked)
- `state="refuted"` → prior=0.0, belief=0.0 (locked)

### Hyperedge (Reasoning Step)
```python
Hyperedge(
    id="auto_generated",
    premise_ids=["node_a", "node_b"],  # premise node IDs
    conclusion_id="node_c",            # conclusion node ID
    module=Module.PLAUSIBLE,           # originating module
    steps=["推理步骤描述"],              # reasoning text
    confidence=0.7,                    # edge confidence [0,1]
    edge_type="heuristic",             # "heuristic" | "formal" | "decomposition"
)
```

**Module types:** PLAUSIBLE, EXPERIMENT, LEAN, ANALOGY, DECOMPOSE, SPECIALIZE, RETRIEVE

**edge_type → Gaia IR mapping:**
- `"heuristic"` → Gaia Strategy type="infer"
- `"formal"` → Gaia Strategy type="deduction"
- `"decomposition"` → Gaia Strategy type="infer"

## Usage

### Create and Save Graph
```python
from dz_hypergraph import create_graph, save_graph
from pathlib import Path

graph = create_graph()
# ... add nodes and edges ...
save_graph(graph, Path("my_reasoning.json"))
```

### Load Graph
```python
from dz_hypergraph import load_graph

graph = load_graph("my_reasoning.json")
for nid, node in graph.nodes.items():
    print(f"[{node.state:10s} b={node.belief:.3f}] {node.statement}")
```

### Bridge to Gaia IR
```python
from dz_hypergraph import bridge_to_gaia, save_gaia_artifacts
from pathlib import Path

# Compile DZ hypergraph to Gaia IR
result = bridge_to_gaia(graph)

# Access compiled results
result.compiled.graph              # gaia.ir.LocalCanonicalGraph
result.compiled.graph.ir_hash      # sha256 hash
result.node_priors                 # {qid: float}
result.strategy_params             # {strategy_id: [cpt]}
result.dz_id_to_qid                # DZ node ID → Gaia QID mapping

# Save standard Gaia artifacts
save_gaia_artifacts(graph, Path("output/"))
# Outputs:
# - output/.gaia/ir.json
# - output/.gaia/ir_hash
# - output/.gaia/reviews/dz_bridge/parameterization.json
# - output/.gaia/reviews/dz_bridge/beliefs.json
```

### Belief Propagation
```python
from dz_hypergraph import propagate_beliefs

# Run BP (uses Gaia BP engine)
iterations = propagate_beliefs(graph)
print(f"BP converged in {iterations} iterations")
```

### Analyze Belief Gaps
```python
from dz_hypergraph import analyze_belief_gaps

# Find weakest links in reasoning chain
for node_id, gain in analyze_belief_gaps(
    graph,
    target_node_id=list(graph.nodes.keys())[-1],
    top_k=3
):
    node = graph.nodes[node_id]
    print(f"Weak point: [{node.belief:.3f}] {node.statement[:50]}... (gain={gain:.3f})")
```

## Architecture

```
DZ HyperGraph (Node/Hyperedge)
    │
    ▼ bridge.py: bridge_to_gaia()
Gaia DSL Runtime (Knowledge/Strategy/Operator)
    │
    ▼ gaia.lang.compiler.compile_package_artifact()
Gaia IR: LocalCanonicalGraph (with ir_hash)
    │
    ├─▶ gaia.ir.validator.validate_local_graph()
    ├─▶ gaia.ir.validator.validate_parameterization()
    │
    ▼ gaia.bp.lowering.lower_local_graph()
Gaia FactorGraph (variables + factors)
    │
    ▼ gaia.bp.engine.InferenceEngine.run()
BP posterior beliefs → write back to DZ Node.belief
```

**Key design:** DZ does NOT reinvent the compiler or BP. All compilation, validation, lowering, and inference are delegated to Gaia components.

## Scripts

- `scripts/validate.py` - Run validation tests

## References

- `references/api.md` - Complete API documentation
- `references/models.md` - Data models reference

## Dependencies

### Required External Repository
```bash
# Clone and install Gaia (core BP and hypergraph logic)
git clone https://github.com/SiliconEinstein/Gaia.git
cd Gaia && pip install -e .
```

### This Skill's Package
- dz-hypergraph package (from gaia-discovery) — **wrapper layer only**

## Architecture Note

```
┌─────────────────────────────────────────┐
│  gaia-hypergraph Skill (this)           │
│  - DZ Node/Hyperedge data models        │
│  - bridge_to_gaia() compilation         │
│  - Skill interface & validation         │
└─────────────────────────────────────────┘
                    │
                    ▼ uses
┌─────────────────────────────────────────┐
│  SiliconEinstein/Gaia                   │
│  - Gaia IR (LocalCanonicalGraph)        │
│  - Gaia Compiler                        │
│  - Gaia Validator                       │
│  - Gaia BP Engine (InferenceEngine)     │
│  - Factor Graph Lowering                │
└─────────────────────────────────────────┘
```

**Zero reimplementation**: All compilation, validation, lowering, and inference
are delegated to Gaia. Upgrading Gaia automatically upgrades this skill's capabilities.

## Related Skills

- **gaia-verify** - Claim extraction and verification
- **gaia-discovery** - MCTS discovery engine
- **gaia-mcp-bridge** - MCP server bridge
