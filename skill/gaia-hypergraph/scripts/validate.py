#!/usr/bin/env python3
"""
Validation script for gaia-hypergraph skill.
Tests basic hypergraph operations without requiring LLM API.
"""

import sys
from pathlib import Path

def check_imports():
    """Check if required packages are available."""
    try:
        from dz_hypergraph import create_graph, save_graph, load_graph
        from dz_hypergraph.models import Node, Hyperedge, Module
        print("✓ dz_hypergraph imports OK")
        return True
    except ImportError as e:
        print(f"✗ dz_hypergraph import failed: {e}")
        print("  Install: pip install -e /path/to/gaia-discovery/packages/dz-hypergraph")
        return False

def check_gaia_imports():
    """Check if Gaia is available."""
    try:
        import gaia
        print("✓ gaia imports OK")
        return True
    except ImportError as e:
        print(f"✗ gaia import failed: {e}")
        print("  Install: git clone https://github.com/SiliconEinstein/Gaia.git && pip install -e Gaia")
        return False

def test_basic_graph():
    """Test basic hypergraph creation."""
    try:
        from dz_hypergraph import create_graph
        from dz_hypergraph.models import Node, Hyperedge, Module

        graph = create_graph()

        # Create nodes
        node_a = Node(
            id="test_a",
            statement="Test premise A",
            belief=0.8,
            prior=0.8,
            state="proven"
        )
        node_b = Node(
            id="test_b",
            statement="Test premise B",
            belief=0.7,
            prior=0.7,
            state="proven"
        )
        node_c = Node(
            id="test_c",
            statement="Test conclusion C",
            belief=0.5,
            prior=0.5,
            state="unverified"
        )

        graph.nodes[node_a.id] = node_a
        graph.nodes[node_b.id] = node_b
        graph.nodes[node_c.id] = node_c

        # Create hyperedge
        edge = Hyperedge(
            id="test_edge",
            premise_ids=["test_a", "test_b"],
            conclusion_id="test_c",
            module=Module.PLAUSIBLE,
            steps=["A and B imply C"],
            confidence=0.6,
            edge_type="heuristic"
        )
        graph.edges[edge.id] = edge

        print(f"✓ Basic graph creation OK (nodes={len(graph.nodes)}, edges={len(graph.edges)})")
        return True
    except Exception as e:
        print(f"✗ Basic graph test failed: {e}")
        return False

def test_bridge():
    """Test Gaia IR bridging (requires Gaia)."""
    try:
        from dz_hypergraph import create_graph, bridge_to_gaia
        from dz_hypergraph.models import Node, Hyperedge, Module

        graph = create_graph()

        # Create simple graph
        node_a = Node(id="a", statement="Premise A", belief=0.9, prior=0.9, state="proven")
        node_b = Node(id="b", statement="Conclusion B", belief=0.5, prior=0.5, state="unverified")
        graph.nodes["a"] = node_a
        graph.nodes["b"] = node_b

        edge = Hyperedge(
            id="e1",
            premise_ids=["a"],
            conclusion_id="b",
            module=Module.PLAUSIBLE,
            steps=["A implies B"],
            confidence=0.7,
            edge_type="heuristic"
        )
        graph.edges["e1"] = edge

        # Bridge to Gaia IR
        result = bridge_to_gaia(graph)

        assert result.compiled.graph is not None
        assert result.compiled.graph.ir_hash is not None
        print(f"✓ Gaia IR bridging OK (ir_hash={result.compiled.graph.ir_hash[:16]}...)")
        return True
    except Exception as e:
        print(f"✗ Gaia IR bridging failed: {e}")
        return False

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("gaia-hypergraph Skill Validation")
    print("=" * 60)

    checks = [
        ("Imports", check_imports),
        ("Gaia Imports", check_gaia_imports),
        ("Basic Graph", test_basic_graph),
        ("Gaia Bridge", test_bridge),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n--- {name} ---")
        results.append(check_fn())

    print("\n" + "=" * 60)
    passed = sum(results)
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
