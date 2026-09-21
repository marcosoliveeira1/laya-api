"""Laya API — wrapper FastAPI sobre a lib `laya` (Router com preload).

Endpoints:
  GET  /health   -> status + modelos residentes
  POST /predict  -> router.predict(state, questions, model?)
  POST /route    -> só a decisão de roteamento, sem forward pass
  POST /preload  -> pré-carrega checkpoints em memória
  POST /unload   -> libera memória
  GET  /presets/{nome} -> schemas prontos (router, guard, moderation, triage)
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("laya-api")

router_obj = None  # laya.Router, carregado no lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router_obj
    from laya import Router

    # preload=True deixa os 3 checkpoints residentes (~4-5GB RAM).
    # Em máquina apertada, use preload=False e chame /preload depois,
    # ou Router(max_loaded=1) para LRU de 1 checkpoint.
    import os

    preload = os.getenv("LAYA_PRELOAD", "true").lower() in ("1", "true", "yes")
    device = os.getenv("LAYA_DEVICE", "cpu")  # oracle-arm: cpu
    log.warning("Carregando Router(preload=%s, device=%s)...", preload, device)
    router_obj = Router(preload=preload, device=device)
    log.warning("Router pronto.")
    yield
    router_obj = None


app = FastAPI(title="Laya API", version="0.1.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    state: dict[str, Any] = Field(description="Estado: texto, email, ticket ou JSON")
    questions: dict[str, Any] = Field(description="Perguntas tipadas choice/score/noul")
    model: Optional[str] = Field(
        default=None,
        description="Override: 'english' | 'multilingual' | 'typed-decisions' (default: auto)",
    )


class PreloadRequest(BaseModel):
    models: Optional[list[str]] = None  # ex: ["english", "multilingual"]


@app.get("/health")
def health():
    ok = router_obj is not None
    return {"status": "ok" if ok else "loading", "router_loaded": ok}


@app.post("/predict")
def predict(req: PredictRequest):
    if router_obj is None:
        raise HTTPException(503, "router ainda carregando")
    try:
        kwargs = {}
        if req.model:
            kwargs["model"] = req.model
        return router_obj.predict(req.state, req.questions, **kwargs)
    except Exception as e:
        log.exception("predict falhou")
        raise HTTPException(500, f"predict falhou: {e}")


@app.post("/route")
def route_only(req: PredictRequest):
    """Só a decisão de roteamento (<0.5ms, sem forward pass)."""
    if router_obj is None:
        raise HTTPException(503, "router ainda carregando")
    try:
        d = router_obj.route(req.state, req.questions)
        return {"model": d.model, "repo": d.repo, "reason": d.reason}
    except Exception as e:
        log.exception("route falhou")
        raise HTTPException(500, f"route falhou: {e}")


@app.post("/preload")
def preload(req: PreloadRequest):
    if router_obj is None:
        raise HTTPException(503, "router ainda carregando")
    try:
        if req.models:
            router_obj.preload(req.models)
        else:
            router_obj.preload()
        return {"status": "ok", "models": req.models or "all"}
    except Exception as e:
        raise HTTPException(500, f"preload falhou: {e}")


@app.post("/unload")
def unload():
    if router_obj is None:
        raise HTTPException(503, "router ainda carregando")
    router_obj.unload()
    return {"status": "ok"}


@app.get("/presets/{nome}")
def preset(nome: str):
    import laya

    presets = {
        "router": laya.router_questions,
        "guard": laya.guard_questions,
        "moderation": laya.moderation_questions,
        "triage": laya.triage_questions,
    }
    fn = presets.get(nome)
    if fn is None:
        raise HTTPException(404, f"preset desconhecido. Use: {sorted(presets)}")
    return fn()
