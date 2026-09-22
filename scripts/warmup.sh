#!/bin/sh
# Warmup pós-deploy (Coolify post-deployment command).
#
# Roda DENTRO do container novo — o Coolify executa com `sh -c`, então:
#   - POSIX sh apenas (sem bashisms: sem [[ ]], sem arrays, sem &>);
#   - só python3 stdlib (a imagem slim não garante curl/wget/jq).
#
# O que faz: espera /health indicar router_loaded=true e chama
# POST /preload {"models": [...]} com o X-API-Key do ambiente.
#
# Uso (campo post-deployment no Coolify, container `laya-api`):
#   sh scripts/warmup.sh
#   sh scripts/warmup.sh multilingual,typed-decisions   # default
# Envs: WARMUP_MODELS (default igual), WARMUP_MAX_WAIT (s, default 1800),
#       WARMUP_POLL (s, default 10), LAYA_API_KEY (auth do /preload).
set -eu

MODELS="${1:-${WARMUP_MODELS:-multilingual,typed-decisions}}"
MAX_WAIT="${WARMUP_MAX_WAIT:-1800}"
POLL="${WARMUP_POLL:-10}"

export WARMUP_MODELS_PARSED="$MODELS" WARMUP_MAX_WAIT="$MAX_WAIT" WARMUP_POLL="$POLL"

echo "[warmup] modelos alvo: $MODELS (max ${MAX_WAIT}s, poll ${POLL}s)"

python3 - <<'PY'
import json
import os
import sys
import time
import urllib.request
import urllib.error

models = [m.strip() for m in os.environ["WARMUP_MODELS_PARSED"].split(",") if m.strip()]
max_wait = int(os.environ.get("WARMUP_MAX_WAIT", "1800"))
poll = int(os.environ.get("WARMUP_POLL", "10"))
api_key = os.environ.get("LAYA_API_KEY", "")
base = "http://localhost:8000"

def get_health():
    with urllib.request.urlopen(base + "/health", timeout=5) as r:
        return json.load(r)

deadline = time.time() + max_wait
while True:
    try:
        h = get_health()
    except Exception as e:
        print("[warmup] /health indisponivel ainda: %s" % e, flush=True)
        h = {}
    if h.get("router_loaded"):
        print("[warmup] router pronto.", flush=True)
        break
    if h.get("status") == "error":
        print("[warmup] ERRO no router: %s" % h.get("error"), flush=True)
        sys.exit(1)
    if time.time() > deadline:
        print("[warmup] TIMEOUT esperando router (>%ss)." % max_wait, flush=True)
        sys.exit(1)
    time.sleep(poll)

body = json.dumps({"models": models}).encode()
req = urllib.request.Request(
    base + "/preload", data=body, headers={"Content-Type": "application/json"},
)
if api_key:
    req.add_header("X-API-Key", api_key)
try:
    # preload pode levar minutos em CPU ARM (torch.load); sem timeout curto.
    with urllib.request.urlopen(req, timeout=max_wait) as r:
        print("[warmup] /preload -> %s" % r.read().decode()[:300], flush=True)
except urllib.error.HTTPError as e:
    print("[warmup] /preload falhou: HTTP %s %s" % (e.code, e.read().decode()[:300]), flush=True)
    sys.exit(1)
print("[warmup] OK: %s residentes." % ",".join(models), flush=True)
PY

echo "[warmup] done."
