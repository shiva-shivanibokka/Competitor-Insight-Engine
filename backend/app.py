"""FastAPI service wrapping the competitor-intelligence pipeline.

Deployed as a Vercel service alongside the Next.js frontend in the same
project, so the browser reaches it same-origin at /api/*.

BYOK (Bring Your Own Key): API keys arrive in each request body, are used
in-memory for that request only, and are NEVER stored, logged, or echoed.
- No key is written to disk or env.
- Request bodies are not logged (uvicorn access log records method/path/status only).
- Error messages reference the provider name, never the key value.
"""

import logging
import os

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from analyzer import list_models
from config import MODEL_TO_PROVIDER, PROVIDERS
from report import run_competitor_intelligence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cie")

# Providers exposed in the frontend, in display order.
FRONTEND_PROVIDERS = ["anthropic", "gemini", "openai", "groq"]

# CORS: the frontend sends BYOK keys but no cookies/credentials, and the server
# holds no secret to protect, so a permissive default is safe for a public demo.
# Same-origin in production anyway; ALLOWED_ORIGINS (comma-separated) narrows it.
_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",")]

app = FastAPI(title="Competitor Intelligence Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

api = APIRouter()


class ModelsRequest(BaseModel):
    provider: str
    llm_key: str = Field(..., min_length=1)  # BYOK — used in-memory only


class ReportRequest(BaseModel):
    company_url: str = Field(..., min_length=1, max_length=2048)
    company_name: str = Field(..., min_length=1, max_length=200)
    provider: str
    model: str
    llm_key: str = Field(..., min_length=1)  # BYOK — used in-memory only
    tavily_key: str = Field(..., min_length=1)  # BYOK — used in-memory only
    max_competitors: int = Field(4, ge=1, le=20)


@api.get("/health")
def health():
    return {"status": "ok"}


@api.get("/providers")
def providers():
    """Drives the frontend's provider + model dropdowns from a single source (config.py)."""
    out = []
    for name in FRONTEND_PROVIDERS:
        p = PROVIDERS[name]
        out.append(
            {
                "id": name,
                "label": p["label"],
                "tier": p["tier"],  # "free" | "paid"
                "key_url": p.get("key_url"),
                "models": [{"name": m, "tier": p["tier"]} for m in p["models"]],
            }
        )
    return {"providers": out}


@api.post("/models")
def models(req: ModelsRequest):
    """The provider's live model list for this key.

    POST rather than GET because the key travels in the body — a key in a query
    string lands in access logs, proxy logs, and browser history.
    """
    if req.provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{req.provider}'.")
    try:
        return {"models": list_models(req.provider, req.llm_key)}
    except Exception as e:
        # Never echo the key; name the provider only.
        raise HTTPException(422, f"Could not list {req.provider} models: {type(e).__name__}") from e


@api.post("/report")
def report(req: ReportRequest):
    # Validate provider/model before doing any work.
    if req.provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{req.provider}'.")
    if MODEL_TO_PROVIDER.get(req.model) != req.provider:
        # config.py's catalogue is allowed to lag: the UI offers the provider's
        # live list, so a valid run can name a model this file has never heard
        # of. Ask the provider rather than refusing — refusing on a stale local
        # list is the bug this endpoint exists to stop repeating.
        try:
            available = list_models(req.provider, req.llm_key)
        except Exception as e:
            raise HTTPException(
                422, f"Could not reach {req.provider} to check '{req.model}': {type(e).__name__}"
            ) from e
        if req.model not in available:
            raise HTTPException(
                400, f"'{req.model}' is not a model your {req.provider} key can use."
            )
        # Only ever caches names the provider itself returned, so this cannot be
        # grown without bound by a caller inventing model names.
        MODEL_TO_PROVIDER[req.model] = req.provider

    log.info("report: company=%r provider=%s model=%s", req.company_name, req.provider, req.model)
    try:
        # One provider/model for the whole run (single model dropdown in the UI).
        markdown = run_competitor_intelligence(
            company_url=req.company_url,
            company_name=req.company_name,
            fast_model=req.model,
            smart_model=req.model,
            max_competitors=req.max_competitors,
            api_keys={req.provider: req.llm_key},
            tavily_key=req.tavily_key,
        )
    except ValueError as e:
        # Expected, user-actionable failures (bad URL, no competitors, missing key).
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        log.exception("pipeline failed")
        raise HTTPException(500, f"Report generation failed: {e}") from e

    return {"report": markdown}


# Mounted twice on purpose. Vercel routes /api/* to this service and forwards
# the path as-is, so production calls /api/report; running uvicorn directly
# (and the notebook, and /docs) calls /report. Registering both means neither
# the local workflow nor the deployed one depends on which of those is true.
app.include_router(api)
app.include_router(api, prefix="/api")
