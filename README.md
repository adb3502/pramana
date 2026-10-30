# Pramana

*pramāṇa* (Sanskrit): a valid means of knowing.

Pramana traces a claim back to the numbers it rests on. Built at Field Station Rajasthan (Logos x Zu-Grama), October 2026.

The project has two parts:

| Part | What it is |
|---|---|
| **Pramana protocol** | A pinned extraction pipeline. Anyone can run it on any paper with their own API keys. The output is a structured record of what the paper reported: estimates, intervals, populations, designs. Each item points to the sentence, table or figure it came from. Two independent extractions of the same paper must agree before the record is accepted. |
| **Pramana app** | One reader of that shared record. Paste a claim and see the studies that measured it, field by field, through a lens or as raw data. |

## Data and lenses

The data layer carries no verdicts. Interpretations such as "inflated", "association read as cause" or "hedge dropped" come from a **lens**: a named, versioned set of rules applied on top of the data. The receipts in the app use *Pramana fidelity lens v1 (adb)*. Anyone can publish another lens over the same data. Where two lenses disagree, a reader sees both.

## Repository layout

```
pipeline/epistemic/   core library: parse, structure, read passes, validate, gate, judge, concepts, closure, graph
pipeline/scripts/     ingest, corpus selection, media claims, citation audit, Wikidata concepts, support and fidelity
pipeline/tests/
docs/CLAIM_MODEL.md   claim model v1: assertion vs proposition, fields, support profile, distortion vector
app/                  the Pramana web app (template.html; build.py inlines a snapshot)
basecamp/             Logos Basecamp modules: receipts-core (C++/Qt, SQLite) and receipts-ui (QML)
deck/                 demo day slides
```

## Links

| | |
|---|---|
| Protocol app (bring your own key) | https://adb3502.github.io/pramana-protocol/ |
| Deck | https://adb3502.github.io/pramana-deck/ |
| Knowledge base snapshot on Logos Storage | `zDvZRwzm1sq9mZA6qVdigHnzPFos7zbzH4QEukk3VLMjhZTxDnGB` |

Fetch the snapshot with `logosctl call storage_module downloadToUrl "<CID>" "$PWD/pramana_snapshot.json" false 65536 false false`.

## Pipeline

| Stage | Steps |
|---|---|
| 1. Sources | PubMed Central full text (JATS); open-access PDFs via OpenAlex; abstracts when there is no open full text, labeled as such; news and posts |
| 2. Read | Parse sections, tables and figures. Reader A is Claude Haiku. Reader B is Laya, a small open model on our own GPU |
| 3. Check | Schema, unit and range validation; agreement gate between the two readers; Claude Sonnet judges disputes |
| 4. Know | Concepts mapped to MeSH and Wikidata IDs; an evidence graph in DuckDB; lenses |
| 5. Share | A content-addressed SQLite snapshot, retrieved from Logos Storage, queried locally in the Basecamp module |

On 30 October 2026 the knowledge base held 1,055 papers across seven topics: coffee and cardiovascular disease, diabetes, aging, caffeine mechanisms, repetitive negative thinking, AI and data center water, and urban simulation. All-in extraction cost was about 14 cents per paper with batching.

Run `pip install -r pipeline/requirements.txt`, then put your keys in `.env`. It is never committed. Then run:

```
python pipeline/scripts/ingest.py --workers 8 PMC1234567
```

## Basecamp modules

```
cd basecamp/receipts-core && nix build '.#lgx-portable'
cd basecamp/receipts-ui && nix build --override-input receipts path:../receipts-core '.#lgx-portable'
```

Install both `.lgx` files in Basecamp from Modules, then Install LGX Package, core first.

## Threat model

| Threat | Defense |
|---|---|
| Tampered snapshot | Content ID mismatch; the module refuses it |
| Model misreads a paper | Two readers and a judge; every number points to its sentence |
| Someone logs what you look up | Queries run on your device |
| Biased verdict | Verdicts live in signed, swappable lenses, never in the data |
| Brigaded community notes | Bridging ratings with stake (planned) |

## Known limits

Paywalled papers are read from the abstract only. Text is English only. 1,055 papers is a sample. Extraction accuracy against human annotators has not yet been measured. Storage retrieval inside Basecamp has not yet been tested end to end.

## License

MIT
