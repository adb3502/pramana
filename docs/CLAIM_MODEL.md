# Claim model v1 (decided 2026-10-28)

The claim is the fundamental unit of the knowledge base. A claim is two objects, never one.

## Assertion
Someone saying something. Fields: `speaker` (author, outlet, account), `source` (document id, URL, hash), `date`, `quote` (shortest verbatim span), `location` (section, sentence, timestamp), `cites` (what the speaker offered as evidence, resolved to documents where possible), `kind` (paper_result, paper_discussion, paper_introduction, press_release, news, blog, social, report, community_note).
Fidelity attaches to assertions.

## Proposition
What was said, normalized and speaker-independent. Fixed fields:

| Field | Content |
|---|---|
| subject | exposure or intervention, as a concept id (Wikidata QID; MeSH kept as an alias where present) |
| object | outcome, as a concept id, plus the measure actually used (MoCA, HR for mortality, WUE) |
| relation | causal, associational, mechanistic, descriptive_quantity, predictive (normative is out of scope) |
| direction | increase, decrease, no_effect, mixed |
| magnitude | measure, value, interval, unit, contrast (or qualitative when no number) |
| population | who, where, when, as a node in a population hierarchy |
| conditions | dose, duration, subgroup, setting |
| modality | hedged, plain, certain |

Evidence (estimates, study designs) attaches to propositions.

## Rules
1. Atomicity: one subject, one object, one relation, one population per proposition. "X lowers A, B and C" is three propositions; the assertion links to all three.
2. Identity: two propositions are the same when subject, object and relation concept ids match and the population nodes are equal. Otherwise they are linked on the ladder.
3. Ladder: propositions form a generality ladder (specific: "RNT, Chinese adults 60+, MoCA" up to general: "negative thinking harms cognition"). Support propagates upward with a loss at every step; the size of the climb between an assertion and its evidence is reported.
4. Normative claims are split into an empirical premise (scored) and a value judgment (labelled, not scored).
5. Nothing is a single score. Two relations are computed and shown field by field:
   * Support (evidence to proposition): matching estimates, weighted by design, counted by independent source, checked for consistency; partial matches record which field differs.
   * Fidelity (assertion to its cited evidence): a distortion vector over the proposition fields, e.g. relation upgraded, outcome proxy treated as the outcome, population overgeneralized, magnitude inflated, hedge dropped.

## Worked example (tweet citing Ye et al. 2025, BMC Psychiatry)
| Field | Paper | Tweet | Distortion |
|---|---|---|---|
| subject | repetitive negative thinking | "negative thinking" | slight broadening |
| object | MoCA score | "your brain" | proxy as outcome |
| relation | associational, cross-sectional | "destroys" | upgraded to causal |
| magnitude | -1.6 points (Q4 vs Q1) | "destroys" | inflated |
| population | Chinese adults 60+, one site | everyone | overgeneralized |
| modality | "further studies needed" | certain | hedge dropped |

## Pitch that follows from this
"An instrument that traces any claim back to the numbers behind it and shows how well those numbers support it. Not a truth score, a receipt."

## Architecture decisions (approved 2026-10-28)
| # | Decision | Choice |
|---|---|---|
| 1 | Concept vocabulary | Wikidata QIDs as the universal anchor; MeSH and other domain vocabularies kept as aliases |
| 2 | Ledger | Hashes of sources and extractions, signed attestations, disputes and lens versions; never raw text |
| 3 | Write access | Machines extract; humans annotate (notes, disputes, missing evidence); nobody edits extracted data |
| 4 | Community quality | Bridging-based rating (a note counts when people who usually disagree both find it helpful) plus per-identity stake or reputation on Logos |
| 5 | Scoring | Versioned, forkable lenses; every score names the lens version that produced it |
| 6 | Compute | Central now (Spark, batch API); later Laya on contributors' machines with spot-check re-runs |
| 7 | Storage | Content-addressed raw store, DuckDB/Postgres graph, open snapshot exports |
| 8 | Product order | Claim checker (link or text in, receipt out), then explorer, then API/MCP for LLMs |
| 9 | Proof | LLM alone vs LLM plus graph on a fixed question set, scored blind |
| 10 | Openness | Open code, open data, public ledger |
Least certain: 4 (whether stakes deter honest experts) and 6 (whether distributed Laya is worth it before scale).
