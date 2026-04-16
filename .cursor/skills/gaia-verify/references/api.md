# gaia-verify API Reference

## Core Functions

### verify_claims()
```python
from dz_verify import verify_claims

summary = verify_claims(
    prose=reasoning_text,           # LLM reasoning output
    context="...",                  # domain context
    graph=graph,                    # HyperGraph instance
    source_memo_id="step_1",        # memo reference
)
```

Extracts claims from text and runs multi-path verification.

Returns `VerificationSummary` with:
- `claims`: List[Claim] - extracted claims
- `results`: List[VerificationResult] - verification outcomes

## Data Models

### Claim
```python
@dataclass
class Claim:
    claim_text: str           # The claim statement
    claim_type: str           # "quantitative" | "structural" | "heuristic"
    context: str              # Domain context
    source_memo_id: str       # Source reference
```

### VerificationResult
```python
@dataclass
class VerificationResult:
    claim: Claim
    verdict: str              # "verified" | "refuted" | "uncertain"
    confidence: float         # [0, 1]
    verification_method: str  # "experiment" | "lean" | "llm_judge"
    details: Dict             # method-specific details
```

## Claim Types

### quantitative
- **Detected by**: numerical assertions, equations, inequalities
- **Verification**: Python code generation + execution
- **Output**: experiment

### structural
- **Detected by**: logical structure, type assertions, properties
- **Verification**: **Lean 4 formal proof** (REQUIRED in strict mode)
- **Output**: lean

### heuristic
- **Detected by**: plausible reasoning, analogies, intuitions
- **Verification**: LLM judge evaluation
- **Output**: llm_judge

## Verification Pipeline

```
Text Input
    │
    ▼ Claim Extraction
Extracted Claims [Claim]
    │
    ▼ Classification
quantitative ──▶ Python Experiment
structural ────▶ Lean 4 Proof (REQUIRED)
heuristic ─────▶ LLM Judge
    │
    ▼ Result Aggregation
VerificationSummary
    │
    ▼ Write to Hypergraph
Updated Graph with verification_source
```

## Configuration

### Required
```bash
LITELLM_PROXY_API_BASE=https://...
LITELLM_PROXY_API_KEY=sk-...
LITELLM_PROXY_MODEL=gpt-4o
```

### Required for Strict Mode
```bash
DISCOVERY_ZERO_LEAN_WORKSPACE=/path/to/lean/workspace
```

### Optional
```bash
DISCOVERY_ZERO_JUDGE_MODEL=gpt-4o-mini    # Separate judge model
```

### Thresholds
```bash
DISCOVERY_ZERO_EXPERIMENT_PRIOR_CAP=0.85
DISCOVERY_ZERO_VERIFIED_PRIOR_FLOOR=0.45
DISCOVERY_ZERO_REFUTATION_PRIOR_MULTIPLIER=0.3
```

## Error Handling

### Strict Mode Errors
- `DISCOVERY_ZERO_LEAN_WORKSPACE not set`: structural claims ERROR
- `Lean workspace not found`: structural claims ERROR
- `Lean compilation failed`: Returns refuted with error details

### Normal Errors
- LLM API failure: Raises exception
- Python execution failure: Returns uncertain
- Lean proof failure: Returns refuted (with error parsing)

## Integration Pattern

```python
from dz_hypergraph import create_graph, propagate_beliefs
from dz_verify import verify_claims

# 1. Create graph
graph = create_graph()

# 2. Verify reasoning
summary = verify_claims(
    prose=llm_output,
    context="...",
    graph=graph,
    source_memo_id="step_1",
)

# 3. Check for refutations
refuted = [r for r in summary.results if r.verdict == "refuted"]
if refuted:
    print(f"Found {len(refuted)} refuted claims, should backtrack")

# 4. Propagate beliefs
propagate_beliefs(graph)
```
