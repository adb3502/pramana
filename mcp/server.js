#!/usr/bin/env node
// Pramana MCP server: lets Claude query the Pramana evidence graph (a local snapshot file)
// alongside its own web search. Read-only. Usage: node server.js [path/to/pramana_snapshot.json]
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const SNAP_PATH = process.argv[2] || process.env.PRAMANA_SNAPSHOT || join(here, "pramana_snapshot.json");
const APP_BASE = process.env.PRAMANA_APP || "https://adb3502.github.io/pramana-app/";
const SNAPSHOT_CID = process.env.PRAMANA_CID || "zDvZRwzm1sq9mZA6qVdigHnzPFos7zbzH4QEukk3VLMjhZTxDnGB";
const D = JSON.parse(readFileSync(SNAP_PATH, "utf8"));
const K = D.K, P = D.P, S = D.S, R = D.R, REC = D.receipts || [];

const norm = s => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const words = q => norm(q).split(" ").filter(w => w.length > 2);
const conceptName = i => (K[i] ? K[i][0] : String(i));
const studyId = i => (S[i] ? S[i][0] : String(i));
const link = id => id.startsWith("PMC") ? `https://pmc.ncbi.nlm.nih.gov/articles/${id}/` : id.startsWith("W") ? `https://openalex.org/${id}` : null;
const RULES = `Write for a reader with no science background, in this structure, with these four plain headings: (1) Short answer: one or two sentences. (2) What the studies found: the numbers the primary research reports, each with its unit, who or what was studied, and the kind of evidence in plain words (measured directly, estimated with a model, a survey, an experiment). Say how sure the authors themselves sound, using their own hedges, and how many independent studies agree or disagree. (3) How it is being reported: what news, company statements and posts say, and exactly where they match, simplify or stretch the studies (a different unit, a missing condition, a stronger word than the authors used). Only include this if web results were used. (4) What we still do not know: the gaps the records themselves show. Cite with numbered footnotes [1], [2] and end with a source list that marks each entry as Pramana record or web. Write every Pramana source as a markdown link to its pramana_url, for example [1] [W4362707075, Making AI Less Thirsty](pramana_url), followed by (original: link) when a link is given. Link web sources to their pages. Describe, do not judge: no verdicts, no slogans, no conclusions beyond what the sources state. Bias-flag counts are not a quality score; do not cite them. This format is the Pramana plain-language lens v1.`;
const out = obj => ({ content: [{ type: "text", text: JSON.stringify(obj, null, 1) }] });

function scoreText(text, ws) { const t = norm(text); let s = 0; for (const w of ws) if (t.includes(w)) s++; return s; }
function matchConcepts(q, limit = 15) {
  const ws = words(q); if (!ws.length) return [];
  const hits = [];
  K.forEach((k, i) => {
    const s = Math.max(scoreText(k[0], ws) * 2, ...(k[2] || []).map(a => scoreText(a, ws)));
    if (s > 0) hits.push({ i, s, n: k[1] });
  });
  hits.sort((a, b) => b.s - a.s || b.n - a.n);
  return hits.slice(0, limit);
}
function pairSummary(p) {
  return { exposure: conceptName(p[0]), outcome: conceptName(p[1]), estimates: p[2], studies: p[3], independent_sources: p[4],
    headline_direction: { lower: p[5], interval_includes_no_effect: p[6], higher: p[7] }, pramana_url: `${APP_BASE}#/pair/${p[0]}/${p[1]}` };
}
function estimatesFor(x, y, limit) {
  const rows = R.filter(r => r[1] === x && r[2] === y).slice(0, limit);
  return rows.map(r => ({ paper: studyId(r[0]), measure: r[3], value: r[4], ci_low: r[5], ci_high: r[6], level: r[7], reference: r[8] }));
}
function paperRecord(i, opts = {}) {
  const s = S[i]; if (!s) return null;
  const rec = { id: s[0], title: s[1], design: s[2], population: s[3], link: link(s[0]),
    author_conclusions: (s[4] || []).map(c => ({ kind: c[0], section: c[1], text: c[2] })),
    cite_as: `[Pramana: ${s[0]}]`, pramana_url: `${APP_BASE}#/paper/${encodeURIComponent(s[0])}` };
  if (opts.bias) rec.bias_flags_top = (s[6] || []).map(b => ({ category: b[0], severity: b[1], note: b[2] }));
  if (opts.estimates) rec.estimates = R.filter(r => r[0] === i).slice(0, opts.estimates).map(r => ({ exposure: conceptName(r[1]), outcome: conceptName(r[2]), measure: r[3], value: r[4], ci_low: r[5], ci_high: r[6], level: r[7], reference: r[8] }));
  return rec;
}

function build() {
const server = new McpServer({ name: "pramana", version: "0.1.0" }, {
  instructions: "Pramana is a structured evidence graph extracted from scientific papers: each record says what a paper measured, in whom, with what estimate and interval, and points to the paper. Use these tools when a question is about what research found. Use your own web search for news, current events and anything outside the graph. When both are used, keep them apart in the answer: say which statements come from Pramana records (cite the paper IDs) and which come from the web. Pramana records carry no verdicts; do not present them as true or false. " + RULES });

server.tool("pramana_about", "What the Pramana knowledge base contains: topics, counts and the Logos Storage content ID of this snapshot.", {}, async () =>
  out({ corpus: D.corpus, counts: D.counts, concepts: K.length, exposure_outcome_pairs: P.length, papers: S.length, snapshot_cid_logos_storage: SNAPSHOT_CID,
    note: "Records are extracted by two independent model readers with disagreements judged; each number links to its paper." }));

server.tool("pramana_search", "Search the evidence graph with a natural-language question or claim. Returns matching concepts, exposure-outcome pairs with study counts and directions, and the most relevant papers with their stated conclusions.",
  { query: z.string().describe("A claim or question, e.g. 'does coffee lower heart failure risk'"), limit: z.number().int().min(1).max(30).optional() },
  async ({ query, limit = 10 }) => {
    const cs = matchConcepts(query, 20), cset = new Set(cs.map(c => c.i));
    const pairs = P.filter(p => cset.has(p[0]) || cset.has(p[1]))
      .map(p => ({ p, s: (cset.has(p[0]) ? 1 : 0) + (cset.has(p[1]) ? 1 : 0) }))
      .sort((a, b) => b.s - a.s || b.p[3] - a.p[3]).slice(0, limit).map(o => pairSummary(o.p));
    const ws = words(query);
    const papers = S.map((s, i) => ({ i, sc: scoreText(s[1], ws) * 2 + (s[4] || []).reduce((a, c) => a + scoreText(c[2], ws), 0) }))
      .filter(o => o.sc > 0).sort((a, b) => b.sc - a.sc).slice(0, limit)
      .map(o => { const r = paperRecord(o.i); r.author_conclusions = r.author_conclusions.slice(0, 4); return r; });
    return out({ answer_rules: RULES, query, matched_concepts: cs.slice(0, 10).map(c => K[c.i][0]), pairs, papers });
  });

server.tool("pramana_evidence", "All extracted estimates for an exposure-outcome pair (concept names as returned by pramana_search), with per-paper values and intervals.",
  { exposure: z.string(), outcome: z.string(), limit: z.number().int().min(1).max(200).optional() },
  async ({ exposure, outcome, limit = 60 }) => {
    const ex = matchConcepts(exposure, 5).map(c => c.i), oc = matchConcepts(outcome, 5).map(c => c.i);
    const pairs = P.filter(p => ex.includes(p[0]) && oc.includes(p[1])).sort((a, b) => b[3] - a[3]);
    if (!pairs.length) return out({ exposure, outcome, found: false, hint: "No pair in the graph. Try pramana_search to see which concept names exist." });
    return out({ answer_rules: RULES, exposure, outcome, pairs: pairs.slice(0, 3).map(p => ({ ...pairSummary(p), estimates: estimatesFor(p[0], p[1], limit) })) });
  });

server.tool("pramana_paper", "Full record for one paper by ID (PMC id like PMC10114037 or OpenAlex id like W4362707075): design, population, stated conclusions with section, bias flags and estimates.",
  { id: z.string() }, async ({ id }) => {
    const i = S.findIndex(s => s[0].toLowerCase() === id.toLowerCase().trim());
    if (i < 0) return out({ id, found: false });
    return out({ answer_rules: RULES, ...paperRecord(i, { bias: true, estimates: 80 }) });
  });

server.tool("pramana_claims", "Search the conclusions papers state about their own findings (association, causal, null, mechanistic), with the section each came from.",
  { query: z.string(), limit: z.number().int().min(1).max(50).optional() }, async ({ query, limit = 20 }) => {
    const ws = words(query), hits = [];
    S.forEach(s => (s[4] || []).forEach(c => { const sc = scoreText(c[2], ws); if (sc) hits.push({ sc, paper: s[0], title: s[1], kind: c[0], section: c[1], text: c[2] }); }));
    hits.sort((a, b) => b.sc - a.sc);
    return out({ answer_rules: RULES, query, claims: hits.slice(0, limit).map(({ sc, ...h }) => h) });
  });

server.tool("pramana_receipts", "Published media claims already compared against the sources they cite (Pramana receipts), interpreted with Pramana fidelity lens v1.",
  {}, async () => out(REC.map(r => ({ id: r.id, outlet: r.outlet, speaker: r.speaker, quote: r.quote, cited: r.cited, found: r.found, verdict_note: r.verdict, fields: r.fields }))));

return server;
}

if (process.env.PRAMANA_HTTP_PORT) {
  const { startHttp } = await import("./http.js");
  startHttp(build, Number(process.env.PRAMANA_HTTP_PORT));
} else {
  await build().connect(new StdioServerTransport());
}
