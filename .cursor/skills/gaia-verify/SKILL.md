---
name: gaia-verify
description: "Claim extraction and multi-path verification for scientific reasoning. Use when: (1) extracting claims from LLM reasoning text, (2) verifying quantitative claims via Python experiments, (3) verifying structural claims via Lean 4 formal proofs, (4) verifying heuristic claims via LLM judge, (5) writing verification results back to hypergraph. NOT for: hypergraph management (use gaia-hypergraph), MCTS discovery (use gaia-discovery), or MCP access (use gaia-mcp-bridge)."
---

# gaia-verify

Claim extraction and multi-path verification for scientific reasoning.
Part of the gaia-discovery ecosystem.

**Behavior**: Matches original gaia-discovery repository. Lean 4 verification is used for structural claims. If Lean workspace is not configured, it will be auto-initialized. If Lean verification fails, the claim is marked as failed/refuted and processing continues (does not exit).

## When to Use

✅ **USE this skill when:**
- Extracting claims from LLM reasoning text
- Verifying **quantitative** claims via Python experiments
- Verifying **structural** claims via **Lean 4 formal proofs** (REQUIRED)
- Verifying **heuristic** claims via LLM judge
- Writing verification results back to hypergraph

❌ **DON'T use this skill when:**
- Managing hypergraphs → use **gaia-hypergraph**
- Running MCTS discovery → use **gaia-discovery**
- Needing MCP access → use **gaia-mcp-bridge**

## Prerequisites

### Required
- Python >= 3.12
- gaia-hypergraph skill (dependency)
- Gaia DSL Runtime: `pip install -e /path/to/Gaia`

### Required for Lean Verification
- Lean 4 installation (optional - will use auto-initialization if not configured)
- `DISCOVERY_ZERO_LEAN_WORKSPACE` (optional - defaults to package's lean_workspace)

### Environment Variables
```bash
# LLM Configuration (required)
LITELLM_PROXY_API_BASE=https://your-llm-proxy.example.com/v1
LITELLM_PROXY_API_KEY=sk-your-key-here
LITELLM_PROXY_MODEL=gpt-4o

# Lean Configuration (optional - auto-initialized if not set)
DISCOVERY_ZERO_LEAN_WORKSPACE=/path/to/lean/workspace  # optional

# Verification Thresholds
DISCOVERY_ZERO_EXPERIMENT_PRIOR_CAP=0.85        # Experiment verification cap
DISCOVERY_ZERO_VERIFIED_PRIOR_FLOOR=0.45        # LLM judge verification floor
DISCOVERY_ZERO_REFUTATION_PRIOR_MULTIPLIER=0.3  # Refutation decay
```

## Claim Types

| Type | Verification Method | Output |
|------|---------------------|--------|
| **quantitative** | Python code execution | experiment |
| **structural** | **Lean 4 formal proof** | **lean** |
| **heuristic** | LLM judge evaluation | llm_judge |

**Lean Behavior** (matches original repository):
- If `DISCOVERY_ZERO_LEAN_WORKSPACE` not set → uses default path and auto-initializes
- If Lean verification fails → claim marked as refuted/failed, processing continues
- No fallback to LLM judge for structural claims

## Usage

### Basic Verification
```python
from dz_hypergraph import create_graph
from dz_verify import verify_claims

graph = create_graph()

reasoning_text = """
首先，因为 n > 2，我们可以对 Fermat 方程 x^n + y^n = z^n 应用模算术。
取模 4 后，若 n 为偶数，则 x^n ≡ 0 或 1 (mod 4)。
"""

# Extract and verify claims
summary = verify_claims(
    prose=reasoning_text,
    context="Fermat's Last Theorem modular arithmetic",
    graph=graph,
    source_memo_id="step_1",
)

# Check results
for result in summary.results:
    print(f"[{result.verdict:12s}] {result.claim.claim_text[:60]}...")
```

### Verification Results
```python
# View extracted claims
for claim in summary.claims:
    print(f"Claim: {claim.claim_text}")
    print(f"Type: {claim.claim_type}")  # quantitative | structural | heuristic

# View verification results
for result in summary.results:
    print(f"Verdict: {result.verdict}")  # verified | refuted | uncertain
    print(f"Confidence: {result.confidence}")
    print(f"Method: {result.verification_method}")  # experiment | lean | llm_judge
```

### Integration with Hypergraph
```python
from dz_hypergraph import propagate_beliefs, analyze_belief_gaps

# Verification results are automatically written to graph
# Run BP to propagate verification results
iterations = propagate_beliefs(graph)

# Find weak points
for node_id, gain in analyze_belief_gaps(graph, target_node_id="...", top_k=3):
    node = graph.nodes[node_id]
    print(f"Weak: [{node.belief:.3f}] {node.statement[:50]}")
```

## Claim Extraction Pipeline

1. **Parse** reasoning text into candidate claims
2. **Classify** each claim as quantitative / structural / heuristic
3. **Route** to appropriate verification method
4. **Execute** verification (Python / Lean / LLM judge)
5. **Parse** verification results
6. **Write** results back to hypergraph nodes

## Verification Methods

### Quantitative → Python Experiment
- Generates Python code from claim
- Executes in sandboxed environment
- Returns: verified / refuted / uncertain

### Structural → Lean 4 Proof (REQUIRED)
- Constructs Lean 4 formal proof
- Compiles with Lean compiler
- Parses compiler errors for feedback
- Returns: verified / refuted / uncertain

**STRICT MODE**: Missing Lean workspace = ERROR

### Heuristic → LLM Judge
- Uses separate judge model (if configured)
- Evaluates claim plausibility
- Returns: verified / refuted / uncertain

## Configuration

### Judge Model Separation
```bash
# Optional: separate model for claim verification
DISCOVERY_ZERO_JUDGE_MODEL=gpt-4o-mini
```

Enables constructor/verifier separation pattern.

### Verification Thresholds
```bash
# Experiment verification caps at this prior
DISCOVERY_ZERO_EXPERIMENT_PRIOR_CAP=0.85

# LLM judge verification floor
DISCOVERY_ZERO_VERIFIED_PRIOR_FLOOR=0.45

# Refutation decay multiplier
DISCOVERY_ZERO_REFUTATION_PRIOR_MULTIPLIER=0.3
```

## Scripts

- `scripts/validate.py` - Run validation tests

## References

- `references/api.md` - Complete API documentation
- `references/claim-types.md` - Claim classification guide
- `references/lean-integration.md` - Lean 4 integration details

## Dependencies

- gaia-hypergraph (this skill depends on it)
- gaia-lang (SiliconEinstein/Gaia)
- dz-verify package (from gaia-discovery)
- Lean 4 (REQUIRED for strict mode)

## Related Skills

- **gaia-hypergraph** - Hypergraph management and BP
- **gaia-discovery** - MCTS discovery engine
- **gaia-mcp-bridge** - MCP server bridge

## Lean Verification Behavior

| Scenario | Behavior |
|----------|----------|
| Lean workspace configured | Uses configured workspace |
| Lean workspace NOT configured | Auto-initializes default workspace |
| Lean proof succeeds | Claim marked as verified |
| Lean proof fails | Claim marked as refuted, processing continues |
| Lean build error | Returns error result, does not exit |

**Note**: Processing continues even if individual claims fail. The verification result is recorded in the hypergraph node.
