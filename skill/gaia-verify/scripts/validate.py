#!/usr/bin/env python3
"""
Validation script for gaia-verify skill.
Tests claim extraction and verification without requiring LLM API.
"""

import sys
from pathlib import Path

def check_imports():
    """Check if required packages are available."""
    try:
        from dz_verify import verify_claims
        from dz_hypergraph import create_graph
        print("✓ dz_verify imports OK")
        return True
    except ImportError as e:
        print(f"✗ dz_verify import failed: {e}")
        print("  Install: pip install -e /path/to/gaia-discovery/packages/dz-verify")
        return False

def check_gaia_hypergraph():
    """Check gaia-hypergraph dependency."""
    try:
        from dz_hypergraph import create_graph, propagate_beliefs
        print("✓ gaia-hypergraph dependency OK")
        return True
    except ImportError as e:
        print(f"✗ gaia-hypergraph dependency failed: {e}")
        return False

def test_claim_extraction():
    """Test claim extraction (no LLM required for parsing)."""
    try:
        from dz_hypergraph import create_graph
        from dz_verify import verify_claims

        graph = create_graph()

        reasoning_text = """
        首先，因为 n > 2，我们可以对 Fermat 方程 x^n + y^n = z^n 应用模算术。
        取模 4 后，若 n 为偶数，则 x^n ≡ 0 或 1 (mod 4)。
        因此 x^n + y^n ≡ 0, 1, 或 2 (mod 4)。
        """

        # This will extract claims (may skip verification without LLM)
        summary = verify_claims(
            prose=reasoning_text,
            context="Fermat's Last Theorem modular arithmetic",
            graph=graph,
            source_memo_id="test_step",
        )

        print(f"✓ Claim extraction OK (claims={len(summary.claims)})")
        return True
    except Exception as e:
        print(f"✗ Claim extraction failed: {e}")
        return False

def test_lean_configuration():
    """Check Lean workspace configuration."""
    import os

    lean_workspace = os.environ.get("DISCOVERY_ZERO_LEAN_WORKSPACE")
    if lean_workspace:
        path = Path(lean_workspace)
        if path.exists():
            print(f"✓ Lean workspace configured: {lean_workspace}")
            return True
        else:
            print(f"⚠ Lean workspace configured but path not found: {lean_workspace}")
            return False
    else:
        print("✗ DISCOVERY_ZERO_LEAN_WORKSPACE not configured")
        print("  STRICT MODE: structural claims will ERROR")
        return False

def test_verification_pipeline():
    """Test verification pipeline (simplified)."""
    import os

    # Skip if no LLM configured
    if not os.environ.get("LITELLM_PROXY_API_KEY"):
        print("⚠ Skipping verification test (no LLM API configured)")
        return True

    try:
        from dz_hypergraph import create_graph
        from dz_verify import verify_claims
        from dz_hypergraph.tools.llm import chat_completion

        # First test basic LLM connectivity
        result = chat_completion(messages=[{'role': 'user', 'content': 'Hello'}])
        print(f"✓ LLM connectivity OK (model: {result.get('model', 'unknown')})")
        
        # Note: Full verify_claims test skipped to avoid long runtime
        print("  Note: Full verify_claims test skipped")
        return True
    except Exception as e:
        print(f"✗ Verification pipeline failed: {e}")
        return False

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("gaia-verify Skill Validation")
    print("=" * 60)

    checks = [
        ("Imports", check_imports),
        ("Hypergraph Dependency", check_gaia_hypergraph),
        ("Claim Extraction", test_claim_extraction),
        ("Lean Configuration", test_lean_configuration),
        ("Verification Pipeline", test_verification_pipeline),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n--- {name} ---")
        results.append(check_fn())

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} checks passed")

    # In strict mode, Lean configuration is required
    import os
    if not os.environ.get("DISCOVERY_ZERO_LEAN_WORKSPACE"):
        print("\n⚠ STRICT MODE WARNING:")
        print("   DISCOVERY_ZERO_LEAN_WORKSPACE not configured.")
        print("   structural claims will ERROR instead of degrading.")

    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    else:
        print("SOME CHECKS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
