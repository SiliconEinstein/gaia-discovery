# Lean 4 Integration

## Overview

Lean 4 integration provides formal verification for structural claims. This skill operates in **STRICT MODE**: Lean verification is mandatory for structural claims.

## Prerequisites

### Lean 4 Installation
```bash
# Install Lean 4 via elan
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
source $HOME/.elan/env

# Verify installation
lean --version
```

### Workspace Structure
```
lean_workspace/
├── lakefile.lean
├── lean-toolchain
└── DZ/
    └── Verify.lean
```

## Configuration

### Required Environment Variable
```bash
export DISCOVERY_ZERO_LEAN_WORKSPACE=/path/to/lean/workspace
```

### Strict Mode Behavior
```python
if not os.environ.get("DISCOVERY_ZERO_LEAN_WORKSPACE"):
    raise RuntimeError(
        "STRICT MODE: DISCOVERY_ZERO_LEAN_WORKSPACE must be set "
        "for structural claim verification. No fallback available."
    )
```

## Verification Flow

```
Structural Claim
    │
    ▼ Generate Lean Code
Lean Theorem Statement
    │
    ▼ Write to Workspace
lean_workspace/DZ/Generated.lean
    │
    ▼ Compile
lake build
    │
    ├─▶ Success → verified
    └─▶ Failure → parse errors → refuted/uncertain
```

## Lean Code Generation

### Example: Transitivity
```lean
-- Claim: "The relation R is transitive"
theorem R_transitive : ∀ x y z, R x y → R y z → R x z := by
  intro x y z h1 h2
  -- Generated proof tactics
  sorry
```

### Example: Group Property
```lean
-- Claim: "This forms a group under composition"
instance : Group G where
  mul := composition
  one := identity
  inv := inverse
  -- Group axioms
  mul_assoc := by sorry
  one_mul := by sorry
  mul_one := by sorry
  mul_left_inv := by sorry
```

## Error Parsing

Lean compiler errors are parsed to provide structured feedback:

| Error Type | Action |
|-----------|--------|
| Type mismatch | Return refuted with details |
| Unknown identifier | Return uncertain (incomplete formalization) |
| Proof incomplete | Return uncertain (tactic failure) |
| Timeout | Return uncertain |

## Workspace Template

### lakefile.lean
```lean
import Lake
open Lake DSL

package «dz-verify» where
  leanOptions := #[
    ⟨`autoImplicit, false⟩
  ]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git"

@[default_target]
lean_lib DZ where
  roots := #[`DZ]
```

### lean-toolchain
```
leanprover/lean4:v4.6.0
```

### DZ/Verify.lean
```lean
import Mathlib

namespace DZ

-- Generated theorems will be inserted here

end DZ
```

## Troubleshooting

### "Lean workspace not found"
```bash
# Check configuration
echo $DISCOVERY_ZERO_LEAN_WORKSPACE

# Verify path exists
ls -la $DISCOVERY_ZERO_LEAN_WORKSPACE
```

### "lake build failed"
```bash
cd $DISCOVERY_ZERO_LEAN_WORKSPACE
lake clean
lake update
lake build
```

### "Unknown identifier" errors
- Claim may require additional definitions
- Formalization may be incomplete
- Returns uncertain (not refuted)

## Performance Considerations

- Lean compilation can be slow for complex proofs
- Consider timeout configuration
- Cache successful compilations when possible

## Security

- Lean code runs in sandboxed environment
- No network access during compilation
- File system access limited to workspace
