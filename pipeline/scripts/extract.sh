#!/usr/bin/env bash
# Run the two blind extractors on one parsed document with headless Claude Code.
# Usage: scripts/extract.sh PMC3439152    (run from the repo root, after parse)
set -euo pipefail
DOC="$1"
mkdir -p ext logs
run () {
  local SIDE="$1" MODEL="$2"
  # prompt seed: a second same-family extractor (B on sonnet) works in a different order so its errors are less correlated with A
  local SEED=""
  [ "$SIDE" = "B" ] && [ "$MODEL" = "sonnet" ] && SEED=" Work in this order: tables last-to-first, then footnotes and captions, then the text from the end of the paper back to the abstract. Decide each candidate from its own context; do not copy decisions across similar-looking candidates without checking."
  ${CLAUDE:-$HOME/.local/bin/claude} -p "Read briefs/EXTRACT_BRIEF.md and follow it exactly. Input: parsed/${DOC}.json. Output: ext/${DOC}.${SIDE}.json. Work only from the input file. Write and run a Python script under work/${DOC}.${SIDE}/ (run it with plain python3, which is the only interpreter you are allowed to call) to build the output and assert the hard rules before writing it. Be exhaustive and precise.${SEED}" \
    --model "$MODEL" \
    --allowedTools "Read" "Write" "Edit" "Bash(python3:*)" "Bash(mkdir:*)" "Bash(ls:*)" \
    --output-format json </dev/null > "logs/${DOC}.${SIDE}.json" 2> "logs/${DOC}.${SIDE}.err"
}
mkdir -p work
# SIDES="A:sonnet B:opus" by default; e.g. SIDES="A:sonnet" or SIDES="B:sonnet" to run one side
for SM in ${SIDES:-A:sonnet B:opus}; do run "${SM%%:*}" "${SM##*:}" & done
wait
for SM in ${SIDES:-A:sonnet B:opus}; do test -s "ext/${DOC}.${SM%%:*}.json" || { echo "missing ${DOC}.${SM%%:*}"; exit 1; }; done
echo "extracted ${DOC}"
