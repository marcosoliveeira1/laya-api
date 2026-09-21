# Laya API

Wrapper FastAPI sobre a lib [`laya`](https://github.com/NandhaKishorM/laya) (`pip`, v0.3.4, Apache 2.0) — motor de decisões tipadas (`choice`/`score`/`noul`) multilíngue, para rodar no **oracle-arm** via Coolify.

Docs interativas: `GET /docs` (Swagger) e `GET /openapi.json`.

## Pré-requisitos

- Python 3.12 (lib exige >= 3.8)
- ~4GB livres em disco (3 checkpoints do HuggingFace, download no primeiro boot)
- ~6GB RAM com `LAYA_PRELOAD=true` (~4–5GB residentes); modo econômico com `LAYA_PRELOAD=false` roda com ~2GB
- Docker + Compose (para rodar via container)

## Rodar local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt
export HF_HOME=./.hf-cache  # cache local dos ~4GB (ver .env.example)
uvicorn app.main:app --port 8000
```

Primeiro boot baixa ~4GB do HuggingFace (3 checkpoints) para `$HF_HOME`. Boots seguintes reutilizam o cache.

## Rodar com Docker Compose

```bash
docker compose up --build
```

Sobe `laya-api` na porta 8000 com volume nomeado `laya-hf` em
`/data/hf-cache` (não rebaixa os ~4GB a cada rebuild) e healthcheck em
`GET /health`. Envs padrão: `LAYA_PRELOAD=true`, `LAYA_DEVICE=cpu`.

## Deploy no Coolify (oracle-arm)

1. Coolify → **+ New Resource → Docker Compose** a partir deste repo
   (arquivo `docker-compose.yml` na raiz).
2. Quase nada a configurar — já vem no compose:
   porta `8000` (interna, sem publicação), volume `laya-hf:/data/hf-cache`,
   healthcheck `GET /health`, rede `shared` (alias `laya-api`),
   `LAYA_PRELOAD=true`, `LAYA_DEVICE=cpu`.
   Só `LAYA_API_KEY` precisa ser cadastrada (ver passo 5).
3. Servidor: `oracle-arm`. RAM: reservar **6GB** (3 checkpoints com preload ~4–5GB).
4. Boot leva minutos na 1ª vez (download dos ~4GB do HF). Acompanhe os logs.

Se a RAM apertar: `LAYA_PRELOAD=false` + `POST /preload {"models": ["english", "multilingual"]}` só com o que for usar.

5. Env `LAYA_API_KEY`: cadastre no Coolify com o token gerado (`openssl rand -hex 32`) — sem ele a API sobe sem auth.
6. Servidor: tem que ser o **mesmo do n8n** (rede `shared` é local ao host; ver "Rede interna" abaixo).

## Configuração

| Var | Default | Descrição |
| --- | --- | --- |
| `LAYA_PRELOAD` | `true` | `true` deixa os 3 checkpoints residentes (~4–5GB). `false` carrega sob demanda via `POST /preload` |
| `LAYA_DEVICE` | `cpu` | Dispositivo torch. No oracle-arm (CPU-only): `cpu` |
| `HF_HOME` | `/data/hf-cache` (Docker) | Diretório do cache do HuggingFace. No local, exporte ex. `./.hf-cache` (ver `.env.example`) |
| `LAYA_API_KEY` | _(vazio = auth off)_ | Token exigido no header `X-API-Key` em tudo exceto `/health`. **Obrigatório em produção.** Gere com `openssl rand -hex 32` |

## Autenticação

Tudo exceto `GET /health` exige o header:

```bash
curl -H "X-API-Key: $LAYA_API_KEY" http://localhost:8000/predict ...
```

Sem `LAYA_API_KEY` setado, a API sobe com auth desativada (log avisa) — ok para dev local, nunca em produção. Resposta sem/com token errado: `401 {"detail": "invalid API key"}`.

## Rede interna (padrão gotenberg)

Sem porta publicada e sem domínio público — igual ao serviço `gotenberg`:
o compose entra na rede externa `shared` com alias `laya-api`, e o n8n
(mesma rede) chama direto:

```
http://laya-api:8000/predict
```

Requisito: deploy no **mesmo servidor/Docker host do n8n** (a rede `shared` é local ao host). Teste local com porta exposta:

```bash
docker compose run -p 8000:8000 laya-api
```

## Uso

Do n8n (rede interna): base `http://laya-api:8000` + header `X-API-Key`.
Do host/local: `http://localhost:8000` (via `docker compose run -p` ou uvicorn).

```bash
# schemas prontos
curl -H "X-API-Key: $LAYA_API_KEY" http://localhost:8000/presets/triage

# só roteamento (<0.5ms, sem inferência)
curl -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' -H "X-API-Key: $LAYA_API_KEY" -d '{
  "state": {"body": "Der Kunde wurde zweimal belastet"},
  "questions": {"dept": {"type": "choice", "instructions": "qual departamento?",
    "criteria": {"billing": "faturas, reembolsos", "technical": "bugs", "other": "resto"}}}
}'

# inferência completa
curl -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' -H "X-API-Key: $LAYA_API_KEY" -d '{
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

Resposta do `/predict` (formato da lib `laya`):

```json
{
  "answers": {
    "department": {"choice": "billing", "confidence": 0.94},
    "urgency": {"score": 1.84},
    "churn_risk": {"noul": 0.892}
  },
  "routing": {
    "model": "english",
    "repo": "convaiinnovations/laya",
    "reason": "English text, routed to ModernBERT-large"
  }
}
```

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/health` | `{"status": "ok", "router_loaded": true}` |
| `POST` | `/predict` | Inferência completa. Body: `{state, questions, model?}` (`model`: `english` \\| `multilingual` \\| `typed-decisions`, default auto) |
| `POST` | `/route` | Só a decisão de roteamento, sem forward pass. Mesmo body do `/predict` |
| `POST` | `/preload` | Pré-carrega checkpoints. Body: `{"models": ["english", "multilingual"]}` ou vazio (= todos) |
| `POST` | `/unload` | Libera checkpoints da memória |
| `GET` | `/presets/{nome}` | Schemas prontos: `router`, `guard`, `moderation`, `triage` |

Primitivas de pergunta: `choice` (label + probs + confiança), `score` (nível ordinal + distribuição), `noul` (P(true) 0–1). Ver doc da lib para o schema completo.

## Laya-API vs Jev (TypeSafe AI)

Mesma ideia — modelo System One: `state` + `questions` tipadas (`choice`/`score`/`noul`) → `answers` com probabilidades, em 1 forward pass. A diferença é **onde roda e quanto custa**.

| | **Este serviço (laya-api)** | **Jev (API hospedada)** |
| --- | --- | --- |
| Modelo | `laya` v0.3.4 (ModernBERT-large 421M EN + mmBERT-base 322M multilíngue + typed-decisions 421M) | `jev-1.13.0` / `jev-latest` (pesos fechados) |
| Pesos | Abertos, Apache 2.0 (`convaiinnovations/laya` no HF) | Fechados, só API gerenciada (waitlist TypeSafe) |
| Onde roda | Self-hosted aqui (oracle-arm, CPU, rede interna `shared`) | Nuvem TypeSafe (`POST https://api.typesafe.ai/v1/systemone`, ctx 64k) |
| Auth | `X-API-Key: $LAYA_API_KEY` (exceto `/health`) | `Authorization: Bearer $JEV_API_KEY` |
| Custo marginal | $0 por chamada (custo é infra: ~4GB disco + ~4–5GB RAM com preload) | $0.042 / 1M input tokens, output free |
| Latência típica | T4 33–40ms/q; **CPU 193–464ms** com preload; 7–10s por troca de idioma sem preload | **70–500ms** fim-a-fim (inclui rede); todas as perguntas em paralelo |
| Multilíngue | 100+ idiomas via `Router` (<0.5ms); 45 de 51 utilizáveis no benchmark | Sem benchmark multilíngue publicado |
| Extras deste wrapper | `POST /route` (só roteamento, sem inferência), `POST /preload`/`/unload`, `GET /presets/{router,guard,moderation,triage}`, `GET /health` sem auth | `usage: {input_tokens, cost_usd}` por resposta; SDKs Python/JS; gateways Vercel/Cloudflare; integração LangChain |

Acurácia (benchmark público `typed-decisions`, 2.000 decisões — números auto-publicados pelo repo `laya`, ver [BENCHMARKS.md](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md); leitura independente em [jev001.org/benchmarks](https://jev001.org/benchmarks/) confirma a ordem de grandeza mas diverge em calibração — fixe a versão antes de decidir):

| Benchmark | Jev 1.13.0 | Laya (routed) |
| --- | --- | --- |
| typed-decisions | 0.727 | **0.766** (+0.039) |
| AG News (4 labels) | 0.910 | **0.950** (+0.040) |
| DAIR Emotion (6 labels) | 0.480 | **0.595** (+0.115) |
| ECE (menor = melhor) | 0.246 | **0.081** (~3× melhor) |
| p50 1 pergunta | 236–276ms (API) | **32.8ms** (T4, ~7.8× mais rápido) |
| Banking77 (77 labels) | **0.870** | 0.425 — **Jev vence folgado acima de ~20 opções** |

Chamada equivalente (só muda base + header):

```bash
# laya-api (interno)
curl -X POST http://laya-api:8000/predict \
  -H 'Content-Type: application/json' -H "X-API-Key: $LAYA_API_KEY" -d '{
  "state": {"body": "Fui cobrado 2x em março."},
  "questions": {"escalate": {"type": "noul", "instructions": "Escalar p/ humano agora?"}}
}'

# Jev (hospedado)
curl https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $JEV_API_KEY" -H 'Content-Type: application/json' -d '{
  "state": {"body": "Fui cobrado 2x em março."},
  "questions": {"escalate": {"type": "noul", "instructions": "Escalar p/ humano agora?"}}
}'
```

**Quando usar qual:**

- Fique no **laya-api** se: quer custo zero por chamada em alto volume, dados não podem sair do servidor (tickets/emails sensíveis ficam na rede `shared`), precisa operar offline, ou quer fine-tunar (pesos abertos, notebook 2xT4 no repo original).
- Prefira o **Jev** se: não quer operar GPU/RAM/disco (~6GB reservados aqui), precisa de >20 labels por pergunta sem coarse-to-fine, ou quer latência previsível sem warm-up/preload.

Números datados de 21/09/2026; ambos os projetos lançaram várias versões na primeira semana — re-rode no seu sample rotulado (algumas centenas de casos reais, separando `choice`/`score`/`noul`) antes de automatizar.

## Integração n8n

Nó HTTP Request → `POST http://laya-api:8000/predict` (rede interna `shared`)
com header `X-API-Key: <token>` e body `{state, questions}`. Gating por confiança no Code/IF seguinte:

```js
const conf = $json.answers.department.confidence;
return [{ keep: conf >= 0.85, ...$json }];
```

Ver `AGENT_CONTEXT.md` para o contexto completo da análise.

## Limitações e operação

Vindas do próprio README/[BENCHMARKS.md](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md) do `laya` — respeite antes de automatizar:

- **Overconfident de fábrica:** o checkpoint inglês colapsa fora do latim (ex. Khmer 0.000 acc a 95% de confiança). O `Router` existe por isso — nunca faça override fixo de `model` em tráfego multilíngue. Calibre temperatura por domínio antes de usar `confidence` para auto-ação (threshold `0.85` acima é ponto de partida, não garantia).
- **>20 opções por pergunta degrada** (Banking77 0.425 vs concorrente 0.870 — orçamento fixo de tokens `head_max_len`). Mitigar com `agent.cfg["head_max_len"]=512` ou coarse-to-fine em 2 etapas.
- **`score` é a primitiva mais fraca** (SST-5 0.372). Prefira `choice`/`noul` para decisões críticas.
- **Latência:** T4 33–40ms/q; CPU 193–464ms com preload. Sem preload, 7–10s por troca de idioma (rebuild). `preload=True` obrigatório em produção.
- **Base ≠ fine-tuned:** checkpoints base ficam ~chance no zero-shot em typed-decisions (0.36 vs baseline maioria 0.461); o 0.766 vem do checkpoint fine-tunado. Trate como "base rápida p/ especializar".

## Troubleshooting

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| `401 {"detail": "invalid API key"}` | `X-API-Key` ausente/errado ou `LAYA_API_KEY` divergente entre Coolify e chamador | Confira o header e a env no Coolify (redeploy após alterar env) |
| Boot leva minutos / health falha no início | Download dos ~4GB na 1ª vez; `lifespan` bloqueia até o `Router` carregar | Acompanhe os logs; `start_period: 180s` já está no compose. Não reduza |
| `503 router ainda carregando` | Requisição durante o preload | Aguarde `/health` → `"router_loaded": true` |
| OOM / container morto | 3 checkpoints + preload > RAM disponível | `LAYA_PRELOAD=false` + `/preload` só do necessário; reserve 6GB no Coolify; mantenha 1 worker |
| Re-download dos pesos a cada deploy | Volume `laya-hf` não persistido | Confira `laya-hf:/data/hf-cache` e `HF_HOME=/data/hf-cache` |
| Resposta lenta alternando idiomas | Sem preload, cada troca rebuilda o checkpoint | `Router(preload=True)` ou `/preload` com os modelos servidos |
| Confiança alta e resposta errada | Overconfidence conhecida (ver Limitações) | Não auto-aja sem calibração; revise threshold; considere fine-tuning (notebook 2xT4 no repo original, 4–5h) |

## Créditos

Este projeto é apenas um wrapper HTTP — todo o motor de decisões é o
[**laya**](https://github.com/NandhaKishorM/laya), de
[NandhaKishorM](https://github.com/NandhaKishorM) / Convai Innovations
(Apache 2.0). Se for usar, considere dar uma estrela no repo original e,
se te ajudar, [apoiar o autor](https://www.buymeacoffee.com/nandakishorm).

Wrapper neste repo: licenciado em Apache 2.0 (ver `LICENSE`).
Atribuições: motor `laya` de NandhaKishorM / Convai Innovations (Apache 2.0) + pesos `convaiinnovations/laya` no HF (Apache 2.0).
