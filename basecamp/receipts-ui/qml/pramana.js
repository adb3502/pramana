.pragma library
.import "pramana_data.js" as PD

// Pramana app logic for Logos Basecamp. Same data model, matching and prompts as the web app
// (adb3502.github.io/pramana-protocol), ported to the QML JavaScript engine.

var CID = 'zDvZRwzm1sq9mZA6qVdigHnzPFos7zbzH4QEukk3VLMjhZTxDnGB';
var RELAY = 'https://identify-sensors-screensaver-homeless.trycloudflare.com';
var MODEL = 'claude-sonnet-4-5';
var STOP = {};
'the a an of and or to in on for with by is are was were be been it its this that than as at from into your you our their his her them they we i me my can could may might will would should does do did not no but also more most less very ultimate just being has have had about over per day study studies new says said found finds shows researchers according how much what which'.split(' ').forEach(function (w) { STOP[w] = 1; });
function stem(w) { return w.replace(/(ing|ed|es|s)$/, '').replace(/ies$/, 'y'); }
function toks(s) { return (String(s == null ? '' : s).toLowerCase().match(/[a-z0-9]+/g) || []).filter(function (w) { return w.length > 2 && !STOP[w]; }).map(stem); }
var EXPAND = [[/negative thinking|overthinking|worry|worrying|brooding/g, ' rumination cognitive '], [/\bbrain\b|memory|thinking skills/g, ' cognition cognitive dysfunction '],
  [/heart disease|heart attack|cardiac/g, ' heart diseases cardiovascular diseases coronary disease '], [/\bdeath\b|die |dying|longevity|lifespan/g, ' mortality '],
  [/blood sugar|glucose/g, ' blood glucose '], [/\bai\b|chatgpt|data cent(er|re)s?/g, ' data center water '], [/\bbp\b/g, ' blood pressure ']];
function expand(q) { var s = ' ' + String(q).toLowerCase() + ' '; EXPAND.forEach(function (e) { s = s.replace(e[0], function (m) { return m + e[1]; }); }); return s; }
var EX = ['How much water does one AI answer use?', 'negative thinking destroys your brain', 'Does coffee lower the risk of heart failure?', 'caffeine and sleep in older adults'];
function fmt(n) { return String(Math.round(Number(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
function plural(n, a, b) { return fmt(n) + ' ' + (n === 1 ? a : b); }
function linkOut(id) { return /^PMC/.test(id) ? 'https://pmc.ncbi.nlm.nih.gov/articles/' + id + '/' : /^W\d+/.test(id) ? 'https://openalex.org/' + id : ''; }
function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

// lens
var LENS = {name: 'Pramana fidelity lens v1', author: 'adb', rules: {
  same: ['match', 'The claim restates the value the source reports.'],
  measure_as_outcome: ['measure read as organ', 'The claim names a broad outcome (the brain, the heart) where the source measured one test score or marker.'],
  upgraded_to_causal: ['association read as cause', 'The claim uses causal verbs (causes, destroys, reduces) where the source design supports association only.'],
  inflated: ['inflated', "The claim's stated or implied size exceeds the source's estimate or its upper interval."],
  overgeneralized: ['overgeneralized', 'The claim applies to a wider population than the source sampled.'],
  strengthened: ['certainty raised', 'The claim states as settled what the source qualified or called preliminary.'],
  hedge_dropped: ['hedge dropped', 'The claim omits a qualifier the source attached to this finding.'],
  omitted: ['omitted', 'The source reports a value for this field and the claim leaves it out.'],
  unverifiable: ['not in record', "The claim's value does not appear in the extracted source record."],
  species_jump: ['animal read as human', 'The source studied animals and the claim speaks of people.'],
  reversed: ['direction reversed', "The claim's direction is opposite to the source's estimate."],
  narrower: ['narrower', 'The claim covers a subset of what the source reported.'],
  broader: ['broader', 'The claim covers more than the source reported.']}};
function lensLabel(k) { return (LENS.rules[k] || [k])[0]; }
function lensRule(k) { return (LENS.rules[k] || ['', ''])[1]; }
function isDiff(k) { return ['same', 'narrower', 'unverifiable'].indexOf(k) < 0; }
function diffCount(r) { return r.fields.filter(function (f) { return isDiff(f[3]); }).length; }

// data
var D = null, K = [], P = [], S = [], R = [], CUR = [], rowsBy = {}, byStudy = {}, sIndex = {}, pairIdx = {}, labelMap = null, deg = null;
function init() {
  if (D) return D;
  D = JSON.parse(PD.SNAP); CUR = JSON.parse(PD.CUR);
  K = D.K.map(function (k, i) {
    var w = {}; toks(k[0]).forEach(function (x) { w[x] = 1; }); (k[2] || []).forEach(function (a) { toks(a).forEach(function (x) { w[x] = 1; }); });
    return {i: i, label: k[0], n: k[1], words: Object.keys(w), lw: toks(k[0])};
  });
  P = D.P.map(function (p) { return {x: p[0], y: p[1], est: p[2], studies: p[3], sources: p[4], lower: p[5], nul: p[6], higher: p[7], noci: p[8]}; });
  S = D.S; R = D.R;
  S.forEach(function (s, i) { sIndex[s[0]] = i; });
  P.forEach(function (p) { pairIdx[p.x + '|' + p.y] = p; });
  R.forEach(function (r) { var k = r[1] + '|' + r[2]; (rowsBy[k] = rowsBy[k] || []).push(r); (byStudy[r[0]] = byStudy[r[0]] || []).push(r); });
  return D;
}
function counts() { init(); return {papers: D.counts.study, sources: D.counts.source, estimates: D.counts.estimate, pairs: P.length, receipts: CUR.length, corpus: D.corpus}; }
function pairRows(x, y) { return rowsBy[x + '|' + y] || []; }

// matching
function conceptScores(q, raw) {
  q = raw ? ' ' + q.toLowerCase() + ' ' : expand(q); var qt = {}; toks(q).forEach(function (w) { qt[w] = 1; }); var out = [];
  K.forEach(function (k) {
    if (!k.lw.length) return;
    var full = k.lw.every(function (w) { return qt[w]; }); var hit = k.words.filter(function (w) { return qt[w]; }).length;
    if (full || hit >= 2) out.push({i: k.i, s: (full ? 2 : 0) + hit / Math.max(k.lw.length, 1) + Math.log(1 + k.n) / Math.LN10 * .15});
  });
  out.sort(function (a, b) { return b.s - a.s; }); var m = {}; out.slice(0, 25).forEach(function (o) { m[o.i] = o.s; }); return m;
}
function matchPairs(q) {
  var cs = conceptScores(q);
  var ps = P.map(function (p) { return {p: p, s: (cs[p.x] || 0) + (cs[p.y] || 0), both: (p.x in cs) && (p.y in cs)}; }).filter(function (o) { return o.s > 0; });
  var both = ps.filter(function (o) { return o.both; }); var L = both.length ? both : ps;
  return L.sort(function (a, b) { return b.s - a.s || b.p.studies - a.p.studies; }).slice(0, 10).map(function (o) { return o.p; });
}
var CT = null, PT = null;
function tset(t) { var o = {}; toks(t).forEach(function (w) { o[w] = 1; }); return o; }
function claimSets() { if (!CT) CT = S.map(function (s) { return (s[4] || []).map(function (c) { return tset(c[2]); }); }); return CT; }
function paperSets() { if (!PT) PT = S.map(function (s) { return tset((s[1] || '') + ' ' + (s[4] || []).map(function (c) { return c[2]; }).join(' ')); }); return PT; }
function findClaims(q, terms) {
  var out = [], cs = claimSets();
  if (terms) {
    var st = terms.subject_terms.map(toks), ot = terms.outcome_terms.map(toks);
    S.forEach(function (s, si) { (s[4] || []).forEach(function (c, ci) { var ct = cs[si][ci];
      var hs = st.filter(function (t) { return t.length && t.every(function (w) { return ct[w]; }); }).length, ho = ot.filter(function (t) { return t.length && t.every(function (w) { return ct[w]; }); }).length;
      if (hs && ho) out.push({h: hs + ho, si: si, c: c}); }); });
  } else {
    var qt = toks(q); if (!qt.length) return [];
    S.forEach(function (s, si) { (s[4] || []).forEach(function (c, ci) { var ct = cs[si][ci]; var h = qt.filter(function (w) { return ct[w]; }).length; if (h >= Math.min(2, qt.length)) out.push({h: h, si: si, c: c}); }); });
  }
  return out.sort(function (a, b) { return b.h - a.h; }).slice(0, 12);
}
function matchCurated(q) {
  for (var i = 0; i < CUR.length; i++) if (CUR[i].re && new RegExp(CUR[i].re, 'i').test(q)) return CUR[i];
  var qt = {}; toks(q).forEach(function (w) { qt[w] = 1; }); var best = null;
  CUR.forEach(function (r) { if (r.sources) return; var rt = toks(r.quote); var h = rt.filter(function (w) { return qt[w]; }).length / Math.max(4, Math.min(rt.length, 10)); if (h >= .35 && (!best || h > best.h)) best = {h: h, r: r}; });
  return best ? best.r : null;
}
function receiptById(id) { for (var i = 0; i < CUR.length; i++) if (CUR[i].id === id) return CUR[i]; return null; }

// direction of one paper's estimates
var RATIO = /^(hr|rr|or|irr|pr|sir|smr|rate ratio|hazard|odds|risk ratio|relative risk|ratio)/i;
function rowDir(r) {
  var lo = r[5], hi = r[6]; if (lo == null || hi == null || isNaN(+lo) || isNaN(+hi)) return 'noci';
  var ref = RATIO.test(String(r[3] || '')) ? 1 : 0;
  return +hi < ref ? 'lower' : +lo > ref ? 'higher' : 'null';
}
function paperDir(rows) {
  var c = {lower: 0, higher: 0, 'null': 0, noci: 0}; rows.forEach(function (r) { c[rowDir(r)]++; });
  if (!(c.lower + c.higher + c['null'])) return 'noci';
  return c.lower > c.higher && c.lower >= c['null'] ? 'lower' : c.higher > c.lower && c.higher >= c['null'] ? 'higher' : 'null';
}
var DHEX = {lower: '#2f6c8f', higher: '#b5652b', 'null': '#a3a9a4', noci: '#cfd2cd'};
var DLAB = {lower: 'lower', higher: 'higher', 'null': 'interval includes no effect', noci: 'no interval'};

// AI search: Claude maps the query to concepts that exist, the app retrieves records locally, Claude describes only those
function degree() { if (deg) return deg; deg = {}; P.forEach(function (p) { deg[p.x] = (deg[p.x] || 0) + p.studies; deg[p.y] = (deg[p.y] || 0) + p.studies; }); return deg; }
function candidates(q) {
  var qt = toks(expand(q)), qs = {}; qt.forEach(function (w) { qs[w] = 1; }); var sc = [];
  K.forEach(function (k) {
    var h = 0; k.words.forEach(function (w) { if (qs[w]) h += 2; else for (var j = 0; j < qt.length; j++) { var t = qt[j]; if (t.length > 3 && (w.indexOf(t) === 0 || t.indexOf(w) === 0)) { h += 1; break; } } });
    if (h) sc.push([k.i, h + Math.log(1 + k.n) / Math.LN10 * .3]);
  });
  sc.sort(function (a, b) { return b[1] - a[1]; });
  var pick = {}, n = 0; sc.slice(0, 120).forEach(function (x) { if (!pick[x[0]]) { pick[x[0]] = 1; n++; } });
  var dg = degree(); Object.keys(dg).map(Number).sort(function (a, b) { return dg[b] - dg[a]; }).forEach(function (i) { if (n < 200 && !pick[i]) { pick[i] = 1; n++; } });
  return Object.keys(pick).map(function (i) { return K[+i].label; });
}
function searchPrompt(q) {
  return 'You turn a search query into a structured lookup for an evidence database built from ' + D.counts.study + ' research papers (' + D.corpus + '). Do not judge whether any claim is true.\n' +
    'Query: """' + q.slice(0, 800) + '"""\nConcepts that exist in the database (use these exact strings only):\n' + JSON.stringify(candidates(q)) + '\n' +
    'Reply with only a JSON object:\n{"intent": one short sentence saying what the person wants to know,\n "fields": {"subject": string, "outcome": string, "relation": "causal"|"associational"|"descriptive"|"comparative"|"quantity"|"not stated", "direction": "increase"|"decrease"|"none"|"not stated", "population": string or "not stated", "certainty": "certain"|"hedged"|"question"|"not stated"},\n "exposure_concepts": [0 to 6 exact concept strings for the exposure or subject],\n "outcome_concepts": [0 to 6 exact concept strings for the outcome],\n "keywords": [3 to 8 short keywords or phrases to find relevant papers by title or stated conclusion]}';
}
function retrieve(q, plan) {
  init();
  if (!labelMap) { labelMap = {}; K.forEach(function (k) { labelMap[k.label.toLowerCase()] = k.i; }); }
  function toIdx(a) { var o = {}; (a || []).forEach(function (x) { var i = labelMap[String(x).toLowerCase()]; if (i != null) o[i] = 1; }); return o; }
  var pairs;
  if (plan) {
    var X = toIdx(plan.exposure_concepts), Y = toIdx(plan.outcome_concepts);
    pairs = P.map(function (p) { var bx = !!X[p.x], by = !!Y[p.y], rx = !!Y[p.x] && !!X[p.y];
      return {p: p, s: (bx && by ? 10 : 0) + (rx ? 6 : 0) + (bx || by ? 2 : 0) + Math.log(1 + p.studies) / Math.LN10}; }).filter(function (o) { return o.s > 3; })
      .sort(function (a, b) { return b.s - a.s; }).slice(0, 12).map(function (o) { return o.p; });
    if (!pairs.length) pairs = matchPairs(q);
  } else pairs = matchPairs(q);
  var kw = plan ? (plan.keywords || []).map(toks).filter(function (t) { return t.length; }) : [toks(q)];
  var ps = {};
  function bump(si, v) { var o = ps[si] || (ps[si] = {si: si, s: 0}); o.s += v; }
  pairs.forEach(function (p, rank) { pairRows(p.x, p.y).forEach(function (r) { bump(r[0], 3 / (1 + rank * .3)); }); });
  var pt = paperSets();
  if (kw.length && kw[0].length) S.forEach(function (s, si) {
    var tt = pt[si];
    var h = kw.filter(function (t) { return t.every(function (w) { return tt[w]; }); }).length; if (h) bump(si, h * 1.5);
  });
  var papers = Object.keys(ps).map(function (k) { return ps[k]; }).sort(function (a, b) { return b.s - a.s; }).slice(0, 40);
  var terms = plan ? {subject_terms: (plan.exposure_concepts || []).concat((plan.keywords || []).slice(0, 2)), outcome_terms: (plan.outcome_concepts || []).concat((plan.keywords || []).slice(2, 4))} : null;
  var claims = findClaims(q, terms && terms.subject_terms.length && terms.outcome_terms.length ? terms : null);
  return {pairs: pairs, papers: papers, claims: claims};
}
function compactEvidence(q, res, plan) {
  var r = matchCurated(q);
  return {query: q, intent: plan && plan.intent,
    pairs: res.pairs.slice(0, 6).map(function (p) { return {exposure: K[p.x].label, outcome: K[p.y].label, studies: p.studies, independent_sources: p.sources,
      headline_direction: {lower: p.lower, includes_no_effect: p.nul, higher: p.higher, no_interval: p.noci},
      estimates: pairRows(p.x, p.y).slice(0, 8).map(function (r) { return {paper: S[r[0]][0], measure: r[3], value: r[4], low: r[5], high: r[6], level: r[7], vs: r[8]}; })}; }),
    papers: res.papers.slice(0, 12).map(function (o) { var s = S[o.si]; return {id: s[0], title: (s[1] || '').slice(0, 160), design: (s[2] || '').slice(0, 100), population: (s[3] || '').slice(0, 100), conclusions: (s[4] || []).slice(0, 3).map(function (c) { return c[2].slice(0, 220); })}; }),
    receipt: r ? {claim: r.quote, fields: r.fields, source_found: r.found} : null};
}
function summaryPrompt(q, res, plan) {
  return 'A person searched an evidence database for: """' + q.slice(0, 800) + '"""\nBelow are the records the database returned. Write 4 to 6 plain sentences on what these records show: what was measured, in whom, how large the estimates are, how consistent they are across papers, and what the records do not cover. Cite papers inline with their IDs in square brackets exactly as given, like [PMC1234567] or [W123456]. Use only these records. Do not use verdict words such as true, false, misleading, debunked, proven, correct or wrong. No headings, no lists.\n\nRecords (JSON):\n' +
    JSON.stringify(compactEvidence(q, res, plan)).slice(0, 60000);
}
function parseJSONLoose(t) {
  try { return JSON.parse(t); } catch (e) {}
  var m = t.match(/```(?:json)?\s*([\s\S]*?)```/); if (m) try { return JSON.parse(m[1]); } catch (e) {}
  var i = t.search(/[\[{]/), j = Math.max(t.lastIndexOf('}'), t.lastIndexOf(']')); if (i >= 0 && j > i) try { return JSON.parse(t.slice(i, j + 1)); } catch (e) {}
  return null;
}
// Streams Claude through the Pramana relay (the key stays on the relay host). onText(full) on each chunk; done(text, err).
function claude(prompt, maxTokens, onText, done) {
  var xhr = new XMLHttpRequest(), seen = 0, buf = '', text = '';
  function pump() {
    var t = xhr.responseText || ''; if (t.length <= seen) return; buf += t.slice(seen); seen = t.length;
    var lines = buf.split('\n'); buf = lines.pop();
    lines.forEach(function (l) { if (l.indexOf('data:') !== 0) return; try { var ev = JSON.parse(l.slice(5)); if (ev.type === 'content_block_delta' && ev.delta && ev.delta.text) { text += ev.delta.text; if (onText) onText(text); } } catch (e) {} });
  }
  xhr.onreadystatechange = function () {
    if (xhr.readyState === 3) pump();
    if (xhr.readyState === 4) {
      if (xhr.status !== 200) { var m = 'HTTP ' + xhr.status; try { m = JSON.parse(xhr.responseText).error.message; } catch (e) {} done(text, xhr.status === 0 ? 'Could not reach the shared Claude relay.' : 'Shared Claude: ' + m); return; }
      pump(); if (buf) { buf += '\n'; pump(); } done(text, null);
    }
  };
  xhr.open('POST', RELAY + '/ai'); xhr.setRequestHeader('content-type', 'application/json');
  xhr.send(JSON.stringify({model: MODEL, max_tokens: maxTokens, stream: true, messages: [{role: 'user', content: prompt}]}));
  return xhr;
}
function citeHtml(t) {
  return esc(t).replace(/\[((?:PMC\d+|W\d+)(?:\s*[,;]\s*(?:PMC\d+|W\d+))*)\]/g, function (m, ids) {
    return ids.split(/\s*[,;]\s*/).map(function (id) { return sIndex[id] != null ? '<a href="paper:' + id + '" style="color:#18301f">' + id + '</a>' : esc(id); }).join(' ');
  }).replace(/\n/g, '<br>');
}

// view models (plain objects for QML)
function pairVM(p) { return {x: p.x, y: p.y, xl: K[p.x].label, yl: K[p.y].label, studies: p.studies, sources: p.sources, est: p.est, lower: p.lower, nul: p.nul, higher: p.higher, noci: p.noci}; }
function paperVM(si) { var s = S[si], rows = byStudy[si] || []; return {si: si, id: s[0], title: s[1] || s[0], design: s[2] || '', population: s[3] || '', n: rows.length, dir: paperDir(rows), color: DHEX[paperDir(rows)]}; }
function claimVM(o) { var s = S[o.si]; return {si: o.si, id: s[0], kind: o.c[0], section: o.c[1], text: o.c[2], title: (s[1] || s[0]).slice(0, 100)}; }
function paperDetail(si) {
  var s = S[si], est = byStudy[si] || [];
  return {si: si, id: s[0], title: s[1] || s[0], design: s[2] || 'not reported', population: s[3] || 'not reported', link: linkOut(s[0]),
    linkName: /^PMC/.test(s[0]) ? 'PubMed Central' : 'OpenAlex', nEst: est.length,
    claims: (s[4] || []).map(function (c) { return {kind: c[0], section: c[1], text: c[2]}; }),
    flags: (s[6] || []).map(function (f) { return {type: String(f[0]).replace(/_/g, ' '), sev: f[1], note: f[2]}; }),
    est: est.slice(0, 120).map(function (r) { return {x: r[1], y: r[2], pair: K[r[1]].label + ' → ' + K[r[2]].label, measure: r[3], value: String(r[4]), ci: r[5] != null ? r[5] + ' to ' + r[6] : 'no interval', level: (r[7] || '') + (r[8] ? '  vs ' + r[8] : '')}; })};
}
function pairDetail(x, y) {
  var p = pairIdx[x + '|' + y]; if (!p) return null;
  var rows = pairRows(x, y).slice().sort(function (a, b) { return a[0] - b[0]; });
  var vm = pairVM(p);
  vm.rows = rows.map(function (r) { var s = S[r[0]]; return {si: r[0], id: s[0], title: (s[1] || s[0]).slice(0, 90), design: (s[2] || '').slice(0, 70), measure: r[3], value: String(r[4]), ci: r[5] != null ? r[5] + ' to ' + r[6] : 'none', level: (r[7] || '') + (r[8] ? '  vs ' + r[8] : ''), dir: rowDir(r)}; });
  return vm;
}
function mapRows(filter, key, dir) {
  var f = toks(filter);
  function lab(p) { return (K[p.x].label + ' ' + K[p.y].label).toLowerCase(); }
  function val(p, k) { return k === 'x' || k === 'y' ? K[p[k]].label.toLowerCase() : p[k]; }
  var rows = P.filter(function (p) { var l = lab(p); return !f.length || f.every(function (w) { return l.indexOf(w) >= 0; }); })
    .sort(function (a, b) { var va = val(a, key), vb = val(b, key); return (va < vb ? -1 : va > vb ? 1 : 0) * dir || b.studies - a.studies; });
  return {total: rows.length, rows: rows.slice(0, 300).map(pairVM)};
}

// graphs: nodes {id, r, fill, stroke, label, tip, kind, si, x, y, ring, pin}, links {s, t, w, o, dist}
function evidenceGraph(q, pairs, extra) {
  var nodes = [{id: 'q', r: 11, fill: '#18301f', stroke: '#ffffff', label: q.length > 42 ? q.slice(0, 40) + '…' : q, tip: q, kind: 'q', pin: true, ring: 0, x: 0, y: 0, charge: -60}], links = [], seen = {}, idx = {q: 0};
  function add(n) { idx[n.id] = nodes.length; nodes.push(n); }
  pairs.forEach(function (p, i) {
    var pid = 'p' + i;
    add({id: pid, r: 7, fill: '#ffffff', stroke: '#18301f', sw: 2, ring: 110, charge: -140, label: (K[p.x].label + ' → ' + K[p.y].label).slice(0, 40), kind: 'pair', x0: p.x, y0: p.y,
      tip: K[p.x].label + ' → ' + K[p.y].label + '\n' + plural(p.studies, 'study', 'studies') + ' · ' + plural(p.est, 'estimate', 'estimates')});
    links.push({s: 'q', t: pid, dist: 110, w: 1.5, o: .8});
    var by = {}, order = []; pairRows(p.x, p.y).forEach(function (r) { if (!by[r[0]]) { by[r[0]] = []; order.push(r[0]); } by[r[0]].push(r); });
    order.slice(0, 14).forEach(function (si) {
      var rows = by[si], s = S[si], d = paperDir(rows), nid = 's' + si;
      if (!seen[nid]) { seen[nid] = 1; add({id: nid, si: si, kind: 'paper', r: 4 + Math.min(8, Math.sqrt(rows.length) * 1.6), fill: DHEX[d], stroke: '#ffffff', ring: 210, charge: -30,
        tip: (s[1] || s[0]).slice(0, 120) + '\n' + s[0] + ' · ' + plural(rows.length, 'estimate', 'estimates') + ' · ' + DLAB[d]}); }
      links.push({s: pid, t: nid, dist: 70, w: 1, o: .6});
    });
  });
  (extra || []).filter(function (o) { return !seen['s' + o.si]; }).slice(0, Math.max(0, 36 - Object.keys(seen).length)).forEach(function (o) {
    var s = S[o.si], rows = byStudy[o.si] || [], d = paperDir(rows), nid = 's' + o.si; seen[nid] = 1;
    add({id: nid, si: o.si, kind: 'paper', r: 4 + Math.min(8, Math.sqrt(rows.length || 1) * 1.6), fill: DHEX[d], stroke: '#ffffff', ring: 170, charge: -30, tip: (s[1] || s[0]).slice(0, 120) + '\n' + s[0] + ' · matched by text'});
    links.push({s: 'q', t: nid, dist: 160, w: .8, o: .35});
  });
  return {nodes: nodes, links: links, radial: true};
}
var DESIGN = [['Trial', /random|trial|rct/i, '#2f6c8f'], ['Cohort', /cohort|prospective|longitudinal|follow-up/i, '#3f7d5a'], ['Case-control', /case.control/i, '#8a6bb0'], ['Cross-sectional', /cross.sectional|survey/i, '#b5652b'], ['Review or meta-analysis', /meta.analys|systematic review|review|pooled/i, '#6d6f2b'], ['Model or other', /./, '#9aa09b']];
function designOf(s) { for (var i = 0; i < DESIGN.length; i++) if (DESIGN[i][1].test(s[2] || '')) return DESIGN[i]; return DESIGN[DESIGN.length - 1]; }
var NET = null;
function paperNet() {
  if (NET) return NET;
  var w = {}, dg = {};
  P.forEach(function (p) { if (p.studies < 2 || p.studies > 25) return; var ss = {}; pairRows(p.x, p.y).forEach(function (r) { ss[r[0]] = 1; }); var a = Object.keys(ss).map(Number);
    for (var i = 0; i < a.length; i++) for (var j = i + 1; j < a.length; j++) { var k = a[i] < a[j] ? a[i] + '|' + a[j] : a[j] + '|' + a[i]; w[k] = (w[k] || 0) + 1; } });
  Object.keys(w).forEach(function (k) { var ab = k.split('|'); dg[ab[0]] = (dg[ab[0]] || 0) + w[k]; dg[ab[1]] = (dg[ab[1]] || 0) + w[k]; });
  return (NET = {w: w, deg: dg});
}
function networkGraph(filter, minShared) {
  init(); var net = paperNet(), f = toks(filter);
  var ids = Object.keys(net.deg).map(Number);
  if (f.length) ids = ids.filter(function (si) { var t = {}; toks((S[si][1] || '') + ' ' + (byStudy[si] || []).slice(0, 60).map(function (r) { return K[r[1]].label + ' ' + K[r[2]].label; }).join(' ')).forEach(function (x) { t[x] = 1; }); return f.every(function (x) { return t[x]; }); });
  ids.sort(function (a, b) { return net.deg[b] - net.deg[a]; }); var capped = ids.length > 300; ids = ids.slice(0, 300); var keep = {}; ids.forEach(function (i) { keep[i] = 1; });
  var links = [], linked = {};
  Object.keys(net.w).forEach(function (k) { var v = net.w[k]; if (v < minShared) return; var ab = k.split('|'); if (keep[ab[0]] && keep[ab[1]]) { links.push({s: 's' + ab[0], t: 's' + ab[1], w: Math.min(4, .6 + v * .5), o: .35, dist: 40, str: .2}); linked[ab[0]] = linked[ab[1]] = 1; } });
  var nodes = ids.filter(function (si) { return linked[si]; }).map(function (si) { var s = S[si], d = designOf(s), n = (byStudy[si] || []).length;
    return {id: 's' + si, si: si, kind: 'paper', r: 3 + Math.min(9, Math.sqrt(n)), fill: d[2], stroke: '#ffffff', charge: -25, tip: (s[1] || s[0]).slice(0, 130) + '\n' + d[0] + ' · ' + plural(n, 'estimate', 'estimates') + ' · ' + s[0]}; });
  return {nodes: nodes, links: links, radial: false, note: plural(nodes.length, 'paper', 'papers') + ', ' + plural(links.length, 'link', 'links') + (capped ? ', the 300 most connected shown' : '')};
}
// force layout (a small port of d3-force: links, many-body, collide, centering, optional radial rings)
function layoutInit(g) {
  var idx = {}; g.nodes.forEach(function (n, i) { idx[n.id] = i; if (n.x == null) { var a = i * 2.39996, rr = 10 * Math.sqrt(i + .5); n.x = rr * Math.cos(a); n.y = rr * Math.sin(a); } n.vx = 0; n.vy = 0; });
  g.links.forEach(function (l) { l.si = idx[l.s]; l.ti = idx[l.t]; });
  var cnt = {}; g.links.forEach(function (l) { cnt[l.si] = (cnt[l.si] || 0) + 1; cnt[l.ti] = (cnt[l.ti] || 0) + 1; });
  g.links.forEach(function (l) { l.bias = cnt[l.si] / (cnt[l.si] + cnt[l.ti]); l.strength = l.str != null ? l.str : Math.min(.6, 1 / Math.min(cnt[l.si], cnt[l.ti])); });
  g.alpha = 1; return g;
}
function layoutTick(g, gx, gy) {
  var N = g.nodes, a = g.alpha; if (a < .003) return false;
  g.links.forEach(function (l) { var s = N[l.si], t = N[l.ti]; var x = t.x + t.vx - s.x - s.vx || 1e-6, y = t.y + t.vy - s.y - s.vy || 1e-6; var d = Math.sqrt(x * x + y * y);
    var k = (d - (l.dist || 60)) / d * a * l.strength; x *= k; y *= k; t.vx -= x * l.bias; t.vy -= y * l.bias; s.vx += x * (1 - l.bias); s.vy += y * (1 - l.bias); });
  for (var i = 0; i < N.length; i++) { var ni = N[i]; for (var j = i + 1; j < N.length; j++) { var nj = N[j]; var dx = nj.x - ni.x || 1e-3, dy = nj.y - ni.y || 1e-3, d2 = dx * dx + dy * dy;
      if (d2 < 90000) { var d2c = Math.max(d2, 25); var fi = (nj.charge || -60) * a / d2c, fj = (ni.charge || -60) * a / d2c; ni.vx += dx * fi; ni.vy += dy * fi; nj.vx -= dx * fj; nj.vy -= dy * fj; }
      var rr = ni.r + nj.r + 2; if (d2 < rr * rr) { var d = Math.sqrt(d2), m = (rr - d) / d * .5; ni.vx -= dx * m * .5; ni.vy -= dy * m * .5; nj.vx += dx * m * .5; nj.vy += dy * m * .5; } } }
  N.forEach(function (n) {
    n.vx -= n.x * (gx || .04) * a; n.vy -= n.y * (gy || .06) * a;
    if (g.radial && n.ring != null) { var d = Math.sqrt(n.x * n.x + n.y * n.y) || 1e-3, k = (n.ring - d) * .5 * a / d; n.vx += n.x * k; n.vy += n.y * k; }
    if (n.pin || n.drag) { n.vx = 0; n.vy = 0; return; }
    n.vx *= .6; n.vy *= .6; n.x += n.vx; n.y += n.vy;
  });
  g.alpha += (0 - g.alpha) * .0228; return true;
}
