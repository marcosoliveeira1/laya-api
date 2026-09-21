"""Laya API — wrapper FastAPI sobre a lib `laya` (Router com preload).

Endpoints:
  GET  /health   -> status + modelos residentes (aberto, sem auth)
  POST /predict  -> router.predict(state, questions, model?)
  POST /route    -> só a decisão de roteamento, sem forward pass
  POST /preload  -> pré-carrega checkpoints em memória
  POST /unload   -> libera memória
  GET  /presets/{nome} -> schemas prontos (router, guard, moderation, triage)

Auth: header `X-API-Key: <LAYA_API_KEY>` em tudo exceto /health.
"""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

log = logging.getLogger("laya-api")

router_obj = None  # laya.Router, carregado em background no lifespan
_load_task: "asyncio.Task | None" = None
_load_error: str | None = None

API_KEY = os.getenv("LAYA_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(key: str | None = Security(api_key_header)):
    """Exige `X-API-Key: <LAYA_API_KEY>` em tudo, exceto /health.

    Sem LAYA_API_KEY setado, auth fica desativada (dev local) com warning no boot.
    """
    if not API_KEY:
        return
    if not key or not secrets.compare_digest(key, API_KEY):
        raise HTTPException(401, "invalid API key")


authed = Depends(verify_api_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Yield primeiro p/ /health responder {"status":"loading"} de imediato,
    depois carrega o Router em background via asyncio.create_task.

    O construtor Router(preload=...) é bloqueante (baixa pesos + torch),
    então roda em asyncio.to_thread p/ não travar o event loop.
    """
    global router_obj, _load_task, _load_error

    # preload=True deixa os 3 checkpoints residentes (~4-5GB RAM).
    # Em máquina apertada, use preload=False e chame /preload depois,
    # ou Router(max_loaded=1) para LRU de 1 checkpoint.
    preload = os.getenv("LAYA_PRELOAD", "true").lower() in ("1", "true", "yes")
    device = os.getenv("LAYA_DEVICE", "cpu")  # oracle-arm: cpu
    if not os.getenv("LAYA_API_KEY"):
        log.warning("LAYA_API_KEY não setado — auth DESATIVADA (ok p/ dev local)")

    def _build_router():
        from laya import Router

        log.warning("Carregando Router(preload=%s, device=%s)...", preload, device)
        obj = Router(preload=preload, device=device)
        log.warning("Router pronto.")
        return obj

    async def _load_in_background():
        global router_obj, _load_error
        try:
            router_obj = await asyncio.to_thread(_build_router)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _load_error = str(e)
            log.exception("Falha ao carregar Router em background")

    _load_task = asyncio.create_task(_load_in_background())
    # Yield imediato: app passa a responder /health (loading) sem esperar pesos.
    yield
    # Shutdown: cancela carga pendente e libera referência.
    if _load_task and not _load_task.done():
        _load_task.cancel()
        try:
            await _load_task
        except asyncio.CancelledError:
            pass
    router_obj = None
    _load_task = None


app = FastAPI(
    title="Laya API",
    version="0.1.0",
    description="Wrapper HTTP sobre a lib `laya` (Router com preload). "
    "Motor de decisões tipadas `choice`/`score`/`noul`. "
    "Auth via header `X-API-Key` (exceto `/health`). "
    "Docs interativas em `/docs`.",
    lifespan=lifespan,
)


class PredictRequest(BaseModel):
    state: dict[str, Any] = Field(
        description="Estado: texto, email, ticket ou JSON",
        examples=[{"from": "user@acme.com", "body": "Fui cobrado 2x em março."}],
    )
    questions: dict[str, Any] = Field(
        description="Perguntas tipadas choice/score/noul",
        examples=[
            {
                "department": {
                    "type": "choice",
                    "instructions": "qual departamento deve atender?",
                    "criteria": {"billing": "faturas, reembolsos", "other": "resto"},
                }
            }
        ],
    )
    model: Optional[str] = Field(
        default=None,
        description="Override: 'english' | 'multilingual' | 'typed-decisions' (default: auto via Router)",
        examples=[None],
    )


class PreloadRequest(BaseModel):
    models: Optional[list[str]] = None  # ex: ["english", "multilingual"]


@app.get("/health", summary="Health check", tags=["ops"])
def health():
    ok = router_obj is not None
    if _load_error is not None:
        return {"status": "error", "router_loaded": False, "error": _load_error}
    return {"status": "ok" if ok else "loading", "router_loaded": ok}


@app.post("/predict", summary="Inferência completa", tags=["inference"], dependencies=[authed])
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


@app.post("/route", summary="Só roteamento, sem inferência", tags=["inference"], dependencies=[authed])
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


@app.post("/preload", summary="Pré-carrega checkpoints", tags=["ops"], dependencies=[authed])
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


@app.post("/unload", summary="Libera checkpoints da memória", tags=["ops"], dependencies=[authed])
def unload():
    if router_obj is None:
        raise HTTPException(503, "router ainda carregando")
    router_obj.unload()
    return {"status": "ok"}


@app.get("/presets/{nome}", summary="Schemas prontos", tags=["schemas"], dependencies=[authed])
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
