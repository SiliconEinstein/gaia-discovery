#!/usr/bin/env python3
"""
Validation script for gaia-discovery skill.
Tests MCTS engine without requiring full LLM API.
"""

import sys
from pathlib import Path

def check_imports():
    """Check if required packages are available."""
    try:
        from dz_engine import run_discovery, MCTSConfig
        print("✓ dz_engine imports OK")
        return True
    except ImportError as e:
        print(f"✗ dz_engine import failed: {e}")
        print("  Install: pip install -e /path/to/gaia-discovery/packages/dz-engine")
        return False

def check_dependencies():
    """Check gaia-hypergraph and gaia-verify dependencies."""
    try:
        from dz_hypergraph import create_graph
        from dz_verify import verify_claims
        print("✓ Dependencies OK (gaia-hypergraph, gaia-verify)")
        return True
    except ImportError as e:
        print(f"✗ Dependency failed: {e}")
        return False

def test_mcts_config():
    """Test MCTS configuration."""
    try:
        from dz_engine import MCTSConfig

        config = MCTSConfig(
            max_iterations=10,
            max_time_seconds=300,
            c_puct=1.4,
            enable_evolutionary_experiments=True,
            enable_continuation_verification=True,
            enable_retrieval=False,
            enable_problem_variants=False,
        )

        assert config.max_iterations == 10
        assert config.c_puct == 1.4
        print("✓ MCTSConfig OK")
        return True
    except Exception as e:
        print(f"✗ MCTSConfig failed: {e}")
        return False

def test_discovery_imports():
    """Test discovery engine imports."""
    try:
        from dz_engine import MCTSDiscoveryEngine
        from dz_engine.analogy import AnalogyEngine
        from dz_engine.decompose import DecomposeEngine
        from dz_engine.specialize import SpecializeEngine

        print("✓ Discovery engine imports OK")
        return True
    except ImportError as e:
        print(f"✗ Discovery engine import failed: {e}")
        return False

def test_graph_creation():
    """Test graph creation for discovery."""
    try:
        from dz_hypergraph import create_graph, save_graph
        from dz_hypergraph.models import Node
        from pathlib import Path
        import tempfile

        graph = create_graph()

        target = Node(
            id="test_target",
            statement="Test conjecture",
            state="unverified",
            belief=0.3,
            prior=0.3,
        )
        graph.nodes[target.id] = target

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)

        save_graph(graph, temp_path)

        print(f"✓ Graph creation OK (nodes={len(graph.nodes)})")

        # Cleanup
        temp_path.unlink()
        return True
    except Exception as e:
        print(f"✗ Graph creation failed: {e}")
        return False

def test_discovery_skipped():
    """Test discovery (simplified - just verify imports and config)."""
    import os

    if not os.environ.get("LITELLM_PROXY_API_KEY"):
        print("⚠ Skipping discovery test (no LLM API configured)")
        return True

    try:
        from dz_engine import run_discovery, MCTSConfig
        
        # Just verify MCTSConfig works
        config = MCTSConfig(
            max_iterations=2,
            max_time_seconds=60,
        )
        
        print(f"✓ Discovery config OK (max_iterations={config.max_iterations})")
        print("  Note: Full discovery test skipped to avoid long runtime")
        return True
    except Exception as e:
        print(f"✗ Discovery test failed: {e}")
        return False

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("gaia-discovery Skill Validation")
    print("=" * 60)

    checks = [
        ("Imports", check_imports),
        ("Dependencies", check_dependencies),
        ("MCTS Config", test_mcts_config),
        ("Discovery Imports", test_discovery_imports),
        ("Graph Creation", test_graph_creation),
        ("Discovery Test", test_discovery_skipped),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n--- {name} ---")
        results.append(check_fn())

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} checks passed")

    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    else:
        print("SOME CHECKS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
