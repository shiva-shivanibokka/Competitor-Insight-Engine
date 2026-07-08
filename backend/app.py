"""FastAPI service wrapping the competitor-intelligence pipeline.

Deploy target: Hugging Face Spaces (Docker SDK). The Next.js frontend on Vercel
calls this directly from the browser.

BYOK (Bring Your Own Key): API keys arrive in each request body, are used
in-memory for that request only, and are NEVER stored, logged, or echoed.
- No key is written to disk or env.
- Request bodies are not logged (uvicorn access log records method/path/status only).
- Error messages reference the provider name, never the key value.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import MODEL_TO_PROVIDER, PROVIDERS
from report import run_competitor_intelligence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cie")

# Providers exposed in the frontend, in display order.
FRONTEND_PROVIDERS = ["anthropic", "gemini", "openai", "groq"]

# CORS: the frontend sends BYOK keys but no cookies/credentials, and the server
# holds no secret to protect, so a permissive default is safe for a public demo.
# Lock it down by setting ALLOWED_ORIGINS (comma-separated) on the Space.
_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",")]

app = FastAPI(title="Competitor Intelligence Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    company_url: str = Field(..., min_length=1, max_length=2048)
    company_name: str = Field(..., min_length=1, max_length=200)
    provider: str
    model: str
    llm_key: str = Field(..., min_length=1)  # BYOK — used in-memory only
    tavily_key: str = Field(..., min_length=1)  # BYOK — used in-memory only
    max_competitors: int = Field(4, ge=1, le=20)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/providers")
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


@app.post("/report")
def report(req: ReportRequest):
    # Validate provider/model against config before doing any work.
    if req.provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{req.provider}'.")
    if MODEL_TO_PROVIDER.get(req.model) != req.provider:
        raise HTTPException(400, f"Model '{req.model}' does not belong to provider '{req.provider}'.")

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
    except Exception as e:  # noqa: BLE001 — surface a clean message, log the rest
        log.exception("pipeline failed")
        raise HTTPException(500, f"Report generation failed: {e}") from e

    return {"report": markdown}
