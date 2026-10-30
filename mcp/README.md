# Pramana MCP server

Lets Claude query the Pramana evidence graph next to its own web search. Read-only, local, no keys.

Tools: `pramana_about`, `pramana_search`, `pramana_evidence`, `pramana_paper`, `pramana_claims`, `pramana_receipts`.

## Install (Claude desktop app)

1. `npm install` in this folder (Node 18+).
2. Get the snapshot: `logosctl call storage_module downloadToUrl "zDvZRwzm1sq9mZA6qVdigHnzPFos7zbzH4QEukk3VLMjhZTxDnGB" "$PWD/pramana_snapshot.json" false 65536 false false`
3. Add to `claude_desktop_config.json`:

```json
{ "mcpServers": { "pramana": { "command": "node", "args": ["/path/to/pramana-mcp/server.js", "/path/to/pramana_snapshot.json"] } } }
```

4. Restart the app. Ask: "Search the web and Pramana for how much water an AI answer uses, and keep the two apart."
