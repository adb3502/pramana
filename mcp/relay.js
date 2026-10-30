// Claude relay for the public Pramana app: the Anthropic key stays on this machine.
// Limits: fixed model, capped output tokens, per-IP rate limit, daily request and spend caps.
const KEY = process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.PRAMANA_MODEL || "claude-sonnet-4-5";
const ORIGINS = (process.env.PRAMANA_ORIGINS || "https://adb3502.github.io").split(",");
const DAILY_USD = Number(process.env.PRAMANA_DAILY_USD || 20);
const DAILY_REQ = Number(process.env.PRAMANA_DAILY_REQ || 800);
const PER_IP = Number(process.env.PRAMANA_PER_IP || 20); // per 10 minutes
const PRICE_IN = 3 / 1e6, PRICE_OUT = 15 / 1e6;

const day = () => new Date().toISOString().slice(0, 10);
let state = { day: day(), req: 0, usd: 0 };
const hits = new Map();

function cors(req, res) {
  const o = req.headers.origin;
  if (o && ORIGINS.includes(o)) { res.setHeader("Access-Control-Allow-Origin", o); res.setHeader("Vary", "Origin"); }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type");
  return !o || ORIGINS.includes(o);
}

export function mountRelay(app) {
  app.options("/ai", (req, res) => { cors(req, res); res.sendStatus(204); });
  app.get("/ai/status", (req, res) => { cors(req, res); if (state.day !== day()) state = { day: day(), req: 0, usd: 0 };
    res.json({ enabled: !!KEY, model: MODEL, requests_today: state.req, spend_today_usd: Math.round(state.usd * 100) / 100, cap_usd: DAILY_USD }); });
  app.post("/ai", async (req, res) => {
    if (!cors(req, res)) return res.status(403).json({ error: { message: "Origin not allowed" } });
    if (!KEY) return res.status(503).json({ error: { message: "Relay has no key" } });
    if (state.day !== day()) state = { day: day(), req: 0, usd: 0 };
    if (state.usd >= DAILY_USD || state.req >= DAILY_REQ) return res.status(429).json({ error: { message: "Today's shared Claude budget is used up. Add your own key with the AI key button." } });
    const ip = (req.headers["cf-connecting-ip"] || req.ip || "x") + "";
    const now = Date.now(), list = (hits.get(ip) || []).filter(t => now - t < 600000);
    if (list.length >= PER_IP) return res.status(429).json({ error: { message: "Too many requests from this address. Try again in a few minutes." } });
    list.push(now); hits.set(ip, list);
    const b = req.body || {};
    const messages = Array.isArray(b.messages) ? b.messages.slice(-4) : null;
    if (!messages || JSON.stringify(messages).length > 120000) return res.status(400).json({ error: { message: "Bad request" } });
    state.req++;
    const upstream = await fetch("https://api.anthropic.com/v1/messages", { method: "POST",
      headers: { "content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model: MODEL, max_tokens: Math.min(Number(b.max_tokens) || 1200, 1500), stream: true, messages }) }).catch(e => null);
    if (!upstream) return res.status(502).json({ error: { message: "Could not reach Anthropic" } });
    if (!upstream.ok) { let t = ""; try { t = await upstream.text(); } catch (e) {} return res.status(upstream.status).type("application/json").send(t || "{}"); }
    res.status(200).setHeader("content-type", "text/event-stream");
    const rd = upstream.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { done, value } = await rd.read(); if (done) break;
      res.write(value);
      buf += dec.decode(value, { stream: true }); const lines = buf.split("\n"); buf = lines.pop();
      for (const l of lines) { if (!l.startsWith("data:")) continue; try { const ev = JSON.parse(l.slice(5));
        if (ev.type === "message_start" && ev.message && ev.message.usage) state.usd += (ev.message.usage.input_tokens || 0) * PRICE_IN;
        if (ev.type === "message_delta" && ev.usage) state.usd += (ev.usage.output_tokens || 0) * PRICE_OUT; } catch (e) {} }
    }
    res.end();
  });
}
