# MCP Protocol

## Overview

Model Context Protocol (MCP) enables standardized communication between AI agents and tools.

## Transport

### stdio (Default)
```
Client process spawns dz-mcp
  -> stdin: JSON-RPC requests
  <- stdout: JSON-RPC responses
```

### SSE (Server-Sent Events)
Alternative for remote connections.

## Message Format

### Request
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "dz_verify_claims",
    "arguments": {
      "prose": "...",
      "context": "..."
    }
  }
}
```

### Response
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "claims_found": 3,
    "verified": 2,
    "refuted": 0
  }
}
```

### Error
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32600,
    "message": "Invalid Request"
  }
}
```

## Capabilities

### Tools
Server exposes tools via `tools/list`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

Response:
```json
{
  "tools": [
    {
      "name": "dz_verify_claims",
      "description": "Extract and verify claims",
      "inputSchema": {...}
    }
  ]
}
```

### Resources
Not currently exposed by gaia-mcp-bridge.

### Prompts
Not currently exposed by gaia-mcp-bridge.

## Lifecycle

1. **Initialize**: Client sends `initialize`
2. **List Tools**: Client queries available tools
3. **Call Tools**: Client invokes tools as needed
4. **Shutdown**: Client closes connection

## Error Codes

| Code | Meaning |
|------|---------|
| -32700 | Parse error |
| -32600 | Invalid request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |

## Security

- Environment variables passed via MCP config
- No persistent state between sessions
- File system access limited to provided paths
- Lean workspace path validated before use
