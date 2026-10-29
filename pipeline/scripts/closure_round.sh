#!/bin/bash
# One closure round on given papers: supplements, figures, structure, pass R (A haiku, B $B_BACKEND) on _S/_F units, validate, closure.
cd ~/epistemic; set -a; . ./.env; set +a; PY=.venv/bin/python; B=${B_BACKEND:-deepseek}; TAG=${TAG:-v2}
for d in "$@"; do
  [ -f parsed/${d}_S.json ] || $PY -m epistemic.supp $d 2>/dev/null | grep "^{"
  $PY -c "import json,sys;F=json.load(open('parsed/${d}_F.json'));sys.exit(0 if all(s['status']=='read' for s in F['sources']) else 1)" 2>/dev/null || $PY -m epistemic.figs $d --force 2>/dev/null | grep "^{"
  [ -f ext/${d}.S4.json ] || $PY -m epistemic.structure $d
  for u in ${d}_S ${d}_F; do
    [ -f parsed/$u.json ] || continue
    $PY -m epistemic.passr A haiku $u; PASSR_CHUNK=60 $PY -m epistemic.passr B $B $u
    $PY -c "from epistemic import validate; import json; r=validate.run('$u'); print(json.dumps({k: r.get(k) for k in ('doc','kappa','role_agreement','n_data','disputes') if k in r}))" 2>&1 | tail -1
  done
done
mkdir -p validation/$TAG; $PY -m epistemic.closure "$@"; cp validation/*.closure.json validation/$TAG/ 2>/dev/null
echo "== done $(date +%H:%M)"
