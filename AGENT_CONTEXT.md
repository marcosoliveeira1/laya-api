# AGENT_CONTEXT — laya-api (para continuar em nova sessão)

## Origem
Análise do repo https://github.com/NandhaKishorM/laya em 21/09/2026, a pedido do Marcos,
que avalia instalar no **oracle-arm** (Oracle a1-flex ARM).

## O que é o laya (fatos verificados no README + pyproject do repo)
- Biblioteca Python (`pip install laya`, v0.3.4, Apache 2.0, Python >=3.8). **Não é app/serviço** — sem Dockerfile, sem API, sem docker-compose no repo. Só `import laya`.
- Motor de decisões tipadas, não-autoregressivo: recebe estado (texto/email/ticket/JSON) + perguntas tipadas e responde em 1 forward pass.
- Primitivas: `choice` (label + probs + confiança), `score` (nível ordinal + distribuição), `noul` (P(true) 0–1).
- 3 checkpoints no HF (`convaiinnovations/laya`, subfolders `multilingual`, `typed-decisions`):
  - `laya`: ModernBERT-large, 421M, ctx 512 — inglês.
  - `laya-multilingual`: mmBERT-base, 322M, ctx 1024 — 100+ idiomas, 2x mais rápido.
  - `laya-typed-decisions`: ModernBERT-large, 421M, ctx 1024 — workflows do benchmark.
- `Router` (entrypoint recomendado): detecta script/idioma em <0.5ms e despacha ao checkpoint certo.
- Presets prontos: `router_questions()`, `guard_questions()`, `moderation_questions()`, `triage_questions()`.
- Deps: `torch>=2.0.0, transformers>=4.45.0, safetensors, huggingface_hub, numpy`.
- Latências publicadas (T4): 1 pergunta 32–40ms; batch 10 → 7–16ms/q. **Em CPU: 193–464ms** com preload; sem preload, 7–10s por troca de idioma (rebuild).
- Limites honestos (do próprio README/BENCHMARKS.md):
  - Base checkpoints ~chance no zero-shot em typed-decisions (0.36 vs baseline maioria 0.461); o 0.766 vem do checkpoint fine-tunado. É "base rápida p/ especializar".
  - >20 opções por pergunta degrada (Banking77 0.425 vs Jev 0.870) — orçamento fixo de tokens `head_max_len`. Mitigar com `agent.cfg["head_max_len"]=512` / ctx maior, ou coarse-to-fine em 2 etapas.
  - `score` é a primitiva mais fraca (SST-5 0.372). Overconfident de fábrica — calibrar temperatura antes de usar confidence p/ auto-ação.
  - Checkpoint inglês colapsa fora do latim (Khmer 0.000 acc a 95% confiança) — por isso o Router existe.

## Servidor oracle-arm (verificado via ssh em 21/09/2026)
- 4 vCPU ARM, 23GB RAM (13GB livres), disco 146GB com 61GB livres, CPU-only, Python 3.12 (sem pip3 no PATH).
- Coolify gerencia os containers. Rede/domínios via Cloudflare + Pangolin no e2-micro.
- Conclusão da análise: **viável** — RAM e disco comportam (~4–5GB RAM com os 3 checkpoints, ~4GB disco p/ pesos). Esperar ~200–500ms/inferência em CPU. `preload=True` obrigatório em produção.

## Este projeto (o que foi scaffoldado)
- `app/main.py`: FastAPI com lifespan (`Router(preload, device)` via env `LAYA_PRELOAD`/`LAYA_DEVICE`), endpoints `/health`, `/predict`, `/route`, `/preload`, `/unload`, `/presets/{router,guard,moderation,triage}`.
- `requirements.txt`: fastapi, uvicorn, pydantic, laya==0.3.4 (torch via índice CPU — ver Dockerfile).
- `Dockerfile`: python:3.12-slim, torch CPU, 1 worker uvicorn, volume `/data/hf-cache`, envs `LAYA_PRELOAD=true LAYA_DEVICE=cpu`.
- `README.md`: como rodar local/Docker/Coolify + exemplos curl + integração n8n.

## Estado / próximos passos sugeridos (nada executado no servidor ainda)
1. [ ] Testar local: `pip install -r requirements.txt && uvicorn app.main:app` e `POST /predict` com exemplo do README.
2. [ ] Validar latência CPU e RAM reais (comparar com 193–464ms publicados).
3. [ ] Subir no Coolify (Dockerfile, porta 8000, volume hf-cache, 6GB RAM, health `/health`).
4. [ ] Expor via Pangolin/Cloudflare se precisar chamar do n8n externo.
5. [ ] Wire no n8n (HTTP Request → /predict → gating por confidence >= 0.85).
6. [ ] Se precisão em domínio específico for insuficiente: fine-tuning (notebook Kaggle 2xT4 no repo, 4–5h) + temperature fitting.
7. [ ] Se >20 labels: implementar coarse-to-fine ou subir `head_max_len`.

## Skills relevantes neste ambiente
- `my-servers` (inventário oracle-arm, ssh), `coolify` (operar apps via API — não fazer curl na mão),
- `token-vault` (credenciais), `n8n-workflows` (criar/operar workflows), `utils-send-message` (WhatsApp).
