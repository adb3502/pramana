# Pramana for Logos Basecamp

Check a claim against an evidence graph built from the literature. Paste a headline, a tweet or a sentence from a paper and get its receipt: the evidence on file for its subject and outcome, what the papers themselves claim, and, when a media item cites a paper, a field-by-field comparison of the claim with what the paper found.

Two modules, following the core + QML pattern of [hackyguru/logos-todo](https://github.com/hackyguru/logos-todo):

- `receipts-core/` (`core`, C++ / Qt SQL): loads a graph snapshot into SQLite under the app data directory and answers `searchPairs`, `searchClaims`, `pairEstimates`, `listReceipts`, `matchReceipt`, `stats`.
- `receipts-ui/` (`ui_qml`): the Basecamp tab. Fetches the snapshot from **Logos Storage** by CID (storage module `downloadToUrl`), loads it, and renders receipts.

## Data on Logos Storage

The graph snapshot (`receipts_snapshot.json`: concepts, exposure-outcome pairs, studies, author claims, 17k estimates, media receipts) is published to Logos Storage and addressed by its CID. The core records the snapshot's SHA-256 and CID, so anyone can check that the receipts they see come from the published graph. Each new graph export is a new CID; the ledger in the extraction pipeline keeps the history.

To publish a snapshot: open Basecamp's file sharing app (storage module), upload `receipts_snapshot.json`, copy the CID and share it with the node's peer record (SPR). In the Pramana tab, paste the CID and SPR and press Fetch, then Load file.

## Build

```bash
cd receipts-core
nix flake update
nix build '.#lgx-portable' --out-link result-portable

cd ../receipts-ui
nix build --override-input receipts path:../receipts-core '.#lgx-portable' --out-link result-portable
```

Install `result-portable/*.lgx` in Basecamp via **Modules → Install LGX Package**, core first, then the UI.

## Status

The core is compiled and tested against Qt 6 with the real snapshot (954 papers load in under a second; searches return in milliseconds). The QML tab and the storage fetch have not yet been run inside Basecamp; the storage call follows the storage module tutorial (`downloadToUrl(cid, destination)` plus the holder's SPR) and may need adjusting to the installed Basecamp version.
