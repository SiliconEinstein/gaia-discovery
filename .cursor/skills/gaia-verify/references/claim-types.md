# Claim Types Guide

## Overview

Claims are classified into three types based on their verifiability characteristics:

| Type | Characteristics | Verification | Strict Mode |
|------|-----------------|--------------|-------------|
| quantitative | Numerical, computable | Python experiment | Required |
| structural | Logical, formalizable | **Lean 4 proof** | **REQUIRED** |
| heuristic | Plausible, intuitive | LLM judge | Required |

## quantitative

### Detection Patterns
- Mathematical equations: `x = y + z`
- Numerical inequalities: `a > b`, `c <= d`
- Computational assertions: `f(n) = O(n^2)`
- Statistical claims: `p-value < 0.05`

### Examples
```
"2 + 2 = 4"
"The runtime is O(n log n)"
"The probability is approximately 0.73"
"For n > 2, x^n + y^n ≠ z^n"
```

### Verification Method
1. Generate Python code from claim
2. Execute in sandboxed environment
3. Compare output with claim
4. Return verified/refuted/uncertain

### Output
- `verification_source`: "experiment"
- `prior`: capped at `DISCOVERY_ZERO_EXPERIMENT_PRIOR_CAP` (default 0.85)

## structural

### Detection Patterns
- Type assertions: "is a prime number"
- Logical properties: "is transitive", "is commutative"
- Structural relationships: "is a subgroup of"
- Formal properties: "is continuous", "is differentiable"

### Examples
```
"The relation R is transitive"
"This forms a group under composition"
"The function is continuous on [0,1]"
"The set is closed under addition"
```

### Verification Method
**STRICT MODE**: Lean 4 formal proof (REQUIRED)

1. Construct Lean 4 theorem statement
2. Generate proof tactics
3. Compile with Lean compiler
4. Parse errors for feedback
5. Return verified/refuted/uncertain

### Output
- `verification_source`: "lean"
- `prior`: high confidence (default 0.99)

### Strict Mode Behavior
```
if DISCOVERY_ZERO_LEAN_WORKSPACE not set:
    raise RuntimeError("Lean workspace required for structural claims")
```

No fallback to LLM judge. Configuration is mandatory.

## heuristic

### Detection Patterns
- Plausible reasoning: "likely", "probably", "suggests"
- Analogical claims: "similar to", "analogous to"
- Intuitive judgments: "reasonable", "plausible"
- Expert intuitions: "it seems that", "appears to be"

### Examples
```
"This approach is likely to succeed"
"The pattern suggests a connection to group theory"
"It is reasonable to assume convergence"
"This is analogous to the proof of Theorem X"
```

### Verification Method
1. Use separate judge model (if configured)
2. Evaluate claim plausibility
3. Return verified/refuted/uncertain

### Output
- `verification_source`: "llm_judge"
- `prior`: floor at `DISCOVERY_ZERO_VERIFIED_PRIOR_FLOOR` (default 0.45)

## Classification Algorithm

Claims are classified based on:
1. Syntactic patterns (keywords, structure)
2. Semantic analysis (LLM-based classification)
3. Context from surrounding text

The classifier outputs one of: `quantitative`, `structural`, `heuristic`

## Verification Result Mapping

| Verdict | Node State | Prior | Belief |
|---------|-----------|-------|--------|
| verified | "proven" | 1.0 | 1.0 |
| refuted | "refuted" | 0.0 | 0.0 |
| uncertain | "unverified" | unchanged | unchanged |

## Best Practices

1. **Always configure Lean workspace** for strict mode
2. **Use separate judge model** for constructor/verifier separation
3. **Review refuted claims** for potential extraction errors
4. **Check uncertain claims** manually when confidence is critical
