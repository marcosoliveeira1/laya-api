# Laya API

Wrapper FastAPI sobre a lib [`laya`](https://github.com/NandhaKishorM/laya) (`pip`, v0.3.4, Apache 2.0) — motor de decisões tipadas (`choice`/`score`/`noul`) multilíngue, para rodar no **oracle-arm** via Coolify.

## Rodar local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Primeiro boot baixa ~4GB do HuggingFace (3 checkpoints). Depois fica em `HF_HOME`.

## Rodar com Docker

```bash
docker build -t laya-api .
docker run -p 8000:8000 -v laya-hf:/data/hf-cache -e LAYA_PRELOAD=true laya-api
```

## Deploy no Coolify (oracle-arm)

1. Coolify → novo **Application** a partir deste repo, tipo **Dockerfile**.
2. Porta: `8000`, health check: `GET /health`.
3. Volume: `/data/hf-cache` (persistir pra não rebaixar os 4GB a cada deploy).
4. RAM: reservar **6GB** (3 checkpoints com preload ~4–5GB).
5. Env: `LAYA_PRELOAD=true`, `LAYA_DEVICE=cpu`.
6. Boot leva minutos na 1ª vez (download). Acompanhe os logs.

Se a RAM apertar: `LAYA_PRELOAD=false` + `POST /preload {"models": ["english", "multilingual"]}` só com o que for usar.

## Uso

```bash
# schemas prontos
curl localhost:8000/presets/triage

# só roteamento (<0.5ms, sem inferência)
curl -X POST localhost:8000/route -H 'Content-Type: application/json' -d '{
  "state": {"body": "Der Kunde wurde zweimal belastet"},
  "questions": {"dept": {"type": "choice", "instructions": "qual departamento?",
    "criteria": {"billing": "faturas, reembolsos", "technical": "bugs", "other": "resto"}}}
}'

# inferência completa
curl -X POST localhost:8000/predict -H 'Content-Type: application/json' -d '{
  "state": {"from": "user@acme.com", "subject": "cobrança duplicada",
            "body": "Fui cobrado 2x em março. Reembolsem hoje ou cancelo."},
  "questions": {
    "department": {"type": "choice", "instructions": "qual departamento deve atender?",
      "criteria": {"billing": "faturas, pagamentos, reembolsos",
                   "technical": "bugs, outages",
                   "sales": "preços, contratos",
                   "other": "resto"}},
    "urgency": {"type": "score", "instructions": "quão urgente?",
      "criteria": ["nada urgente", "em breve", "crítico/bloqueante"]},
    "churn_risk": {"type": "noul", "instructions": "o usuário ameaça cancelar?"}
  }
}'
```

## Integração n8n

Nó HTTP Request → `POST http://<host>:8000/predict` com `{state, questions}`. Gating por confiança no Code/IF seguinte:

```js
const conf = $json.answers.department.confidence;
return [{ keep: conf >= 0.85, ...$json }];
```

Ver `AGENT_CONTEXT.md` para o contexto completo da análise.

## Créditos

Este projeto é apenas um wrapper HTTP — todo o motor de decisões é o
[**laya**](https://github.com/NandhaKishorM/laya), de
[NandhaKishorM](https://github.com/NandhaKishorM) / Convai Innovations
(Apache 2.0). Se for usar, considere dar uma estrela no repo original e,
se te ajudar, [apoiar o autor](https://www.buymeacoffee.com/nandakishorm).
