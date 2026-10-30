// Streamable HTTP transport for remote use (claude.ai custom connector). Stateless: one server per request.
import express from "express";
import { mountRelay } from "./relay.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
export function startHttp(build, port) {
  const app = express();
  app.set("trust proxy", true);
  app.use(express.json({ limit: "1mb" }));
  mountRelay(app);
  app.get("/", (_q, res) => res.type("text/plain").send("Pramana MCP server. Add <this URL>/mcp as a custom connector in Claude."));
  app.post("/mcp", async (req, res) => {
    try {
      const server = build();
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      res.on("close", () => { transport.close(); server.close(); });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (e) {
      if (!res.headersSent) res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal error" }, id: null });
    }
  });
  const na = (_q, res) => res.status(405).json({ jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed" }, id: null });
  app.get("/mcp", na); app.delete("/mcp", na);
  app.listen(port, "127.0.0.1", () => console.error(`pramana mcp http on 127.0.0.1:${port}/mcp`));
}
