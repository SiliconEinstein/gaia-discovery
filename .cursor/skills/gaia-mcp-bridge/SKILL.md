---
name: gaia-mcp-bridge
description: "MCP server bridge for gaia-discovery ecosystem. Use when: (1) exposing gaia-discovery capabilities via MCP protocol, (2) integrating with Cursor, Claude Desktop, or other MCP clients, (3) providing standardized tool access to hypergraph operations, claim verification, and discovery. NOT for: direct hypergraph use (use gaia-hypergraph), direct verification (use gaia-verify), direct discovery (use gaia-discovery)."
---

# gaia-mcp-bridge

MCP server bridge for gaia-discovery ecosystem.
Exposes gaia-discovery capabilities via Model Context Protocol (MCP).

## When to Use

✅ **USE this skill when:**
- Exposing gaia-discovery capabilities via MCP protocol
- Integrating with Cursor, Claude Desktop, or other MCP clients
- Providing standardized tool access to hypergraph operations
- Enabling external agents to use verification and discovery

❌ **DON'T use this skill when:**
- Using hypergraphs directly → use **gaia-hypergraph**
- Verifying claims directly → use **gaia-verify**
- Running discovery directly → use **gaia-discovery**

## Prerequisites

### Required
- Python >= 3.12
- gaia-hypergraph, gaia-verify, gaia-discovery (dependencies)
- Gaia DSL Runtime: `pip install -e /path/to/Gaia`

### MCP Client Configuration

#### Cursor
Create `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "gaia": {
      "command": "dz-mcp",
      "args": [],
      "env": {
        "LITELLM_PROXY_API_BASE": "https://your-proxy.example.com/v1",
        "LITELLM_PROXY_API_KEY": "sk-...",
        "LITELLM_PROXY_MODEL": "gpt-4o",
        "DISCOVERY_ZERO_LEAN_WORKSPACE": "/path/to/lean"
      }
    }
  }
}
```

#### Claude Desktop
Add to Claude Desktop config:
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

## MCP Tools

| Tool | Description |
|------|-------------|
| `dz_extract_claims` | Extract claims from reasoning text |
| `dz_verify_claims` | Extract + verify + write to hypergraph |
| `dz_propagate_beliefs` | Run Bayesian belief propagation |
| `dz_analyze_gaps` | Analyze belief gaps in reasoning chain |
| `dz_load_graph` | Load hypergraph from file |
| `dz_run_discovery` | Run full MCTS discovery process |

## Usage

### Start MCP Server
```bash
# Start stdio server
dz-mcp

# Or with explicit env
LITELLM_PROXY_API_BASE=... LITELLM_PROXY_API_KEY=... dz-mcp
```

### Tool Examples

#### dz_extract_claims
```json
{
  "prose": "First, because n > 2, we can apply modular arithmetic...",
  "context": "Fermat's Last Theorem"
}
```

Returns:
```json
{
  "claims": [
    {"text": "...", "type": "quantitative"},
    {"text": "...", "type": "structural"}
  ]
}
```

#### dz_verify_claims
```json
{
  "prose": "...",
  "context": "...",
  "graph_path": "/path/to/graph.json",
  "source_memo_id": "step_1"
}
```

Returns:
```json
{
  "claims_found": 3,
  "verified": 2,
  "refuted": 0,
  "uncertain": 1,
  "results": [...]
}
```

#### dz_run_discovery
```json
{
  "graph_path": "/path/to/conjecture.json",
  "target_node_id": "conjecture_1",
  "max_iterations": 20,
  "max_time_seconds": 1800,
  "model": "gpt-4o"
}
```

Returns:
```json
{
  "iterations_completed": 20,
  "target_belief_initial": 0.3,
  "target_belief_final": 0.85,
  "success": true,
  "elapsed_seconds": 1200
}
```

## Architecture

```
MCP Client (Cursor/Claude)
    │
    ▼ MCP Protocol (stdio/sse)
dz-mcp Server
    │
    ├─▶ gaia-hypergraph (graph ops)
    ├─▶ gaia-verify (verification)
    └─▶ gaia-discovery (MCTS)
```

## Scripts

- `scripts/validate.py` - Run validation tests

## References

- `references/api.md` - Complete API documentation
- `references/mcp-protocol.md` - MCP protocol details

## Dependencies

- gaia-hypergraph (dependency)
- gaia-verify (dependency)
- gaia-discovery (dependency)
- dz-mcp package (from gaia-discovery)

## Related Skills

- **gaia-hypergraph** - Hypergraph management
- **gaia-verify** - Claim verification
- **gaia-discovery** - MCTS discovery

## Security Notes

- MCP server runs with client-provided environment
- Lean workspace path is passed via env
- API keys should be configured in MCP client, not hardcoded
