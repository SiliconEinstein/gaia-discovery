# gaia-mcp-bridge API Reference

## MCP Tools

### dz_extract_claims

Extract claims from reasoning text.

**Input:**
```json
{
  "prose": "Reasoning text here...",
  "context": "Domain context"
}
```

**Output:**
```json
{
  "claims": [
    {
      "text": "Claim statement",
      "type": "quantitative|structural|heuristic"
    }
  ]
}
```

### dz_verify_claims

Extract, verify, and write results to hypergraph.

**Input:**
```json
{
  "prose": "Reasoning text...",
  "context": "Domain context",
  "graph_path": "/path/to/graph.json",
  "source_memo_id": "step_1"
}
```

**Output:**
```json
{
  "claims_found": 3,
  "verified": 2,
  "refuted": 0,
  "uncertain": 1,
  "results": [
    {
      "claim": "...",
      "verdict": "verified|refuted|uncertain",
      "confidence": 0.85,
      "method": "experiment|lean|llm_judge"
    }
  ]
}
```

### dz_propagate_beliefs

Run Bayesian belief propagation.

**Input:**
```json
{
  "graph_path": "/path/to/graph.json"
}
```

**Output:**
```json
{
  "iterations": 15,
  "converged": true
}
```

### dz_analyze_gaps

Analyze belief gaps in reasoning chain.

**Input:**
```json
{
  "graph_path": "/path/to/graph.json",
  "target_node_id": "node_id",
  "top_k": 5
}
```

**Output:**
```json
{
  "gaps": [
    {
      "node_id": "...",
      "statement": "...",
      "belief": 0.3,
      "information_gain": 0.7
    }
  ]
}
```

### dz_load_graph

Load hypergraph from file.

**Input:**
```json
{
  "graph_path": "/path/to/graph.json"
}
```

**Output:**
```json
{
  "nodes": 10,
  "edges": 5,
  "loaded": true
}
```

### dz_run_discovery

Run full MCTS discovery process.

**Input:**
```json
{
  "graph_path": "/path/to/conjecture.json",
  "target_node_id": "conjecture_1",
  "max_iterations": 20,
  "max_time_seconds": 1800,
  "model": "gpt-4o",
  "c_puct": 1.4
}
```

**Output:**
```json
{
  "iterations_completed": 20,
  "target_belief_initial": 0.3,
  "target_belief_final": 0.85,
  "success": true,
  "elapsed_seconds": 1200,
  "best_bridge_plan": {
    "steps": [...],
    "confidence": 0.82
  }
}
```

## Server Configuration

### Environment Variables

All tools require:
```bash
LITELLM_PROXY_API_BASE=https://...
LITELLM_PROXY_API_KEY=sk-...
LITELLM_PROXY_MODEL=gpt-4o
```

For structural claim verification:
```bash
DISCOVERY_ZERO_LEAN_WORKSPACE=/path/to/lean
```

### Cursor Configuration

`.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "gaia": {
      "command": "dz-mcp",
      "args": [],
      "env": {
        "LITELLM_PROXY_API_BASE": "...",
        "LITELLM_PROXY_API_KEY": "...",
        "DISCOVERY_ZERO_LEAN_WORKSPACE": "..."
      }
    }
  }
}
```

### Claude Desktop Configuration

Claude Desktop config:
```json
{
  "mcpServers": {
    "gaia": {
      "command": "dz-mcp",
      "env": {
        "LITELLM_PROXY_API_BASE": "...",
        "LITELLM_PROXY_API_KEY": "..."
      }
    }
  }
}
```

## Protocol

MCP uses stdio transport by default:

```
Client -> stdin -> dz-mcp
Client <- stdout <- dz-mcp
```

Messages are JSON-RPC 2.0 formatted.
