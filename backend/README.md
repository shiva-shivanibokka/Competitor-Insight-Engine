# Competitor Intelligence Engine — Backend API

FastAPI service that runs the competitor-intelligence pipeline. It is deployed
as the `api` service of this repo's Vercel project (see `vercel.json`), so the
frontend reaches it same-origin at `/api/*`.

## Endpoints

| Method | Path         | Purpose                                            |
|--------|--------------|----------------------------------------------------|
| GET    | `/health`    | Liveness check                                     |
| GET    | `/providers` | Provider + model catalog (drives the UI dropdowns) |
| POST   | `/models`    | The models a given key can actually use            |
| POST   | `/report`    | Run the pipeline, return the Markdown report       |

Every route is registered twice — bare (`/health`) and prefixed (`/api/health`).
Vercel routes `/api/*` to this service and forwards the path unchanged, while
uvicorn locally, `/docs`, and the notebook use the bare paths. Registering both
means the deployed and local workflows do not disagree about the same code.

`POST /report` body:

```json
{
  "company_url": "https://stripe.com",
  "company_name": "Stripe",
  "provider": "anthropic",
  "model": "claude-sonnet-5",
  "llm_key": "<user's provider key>",
  "tavily_key": "<user's tavily key>",
  "max_competitors": 4
}
```

`POST /models` takes `{"provider": "...", "llm_key": "..."}` and returns the
provider's live model list. The UI calls it as soon as a key is entered and
replaces its dropdown with the result. `config.py`'s catalogue is only a
starting point: it once offered `claude-3-haiku-20240307` months after the
provider retired it, and anyone who picked it got a 404 mid-run.

## BYOK — keys never leak

API keys arrive per request, are used **in-memory for that request only**, and
are never stored, logged, or echoed. Request bodies are not logged; error
messages name the provider, never the key.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 7860
# open http://localhost:7860/docs
```

Interactive API tests need real keys, either in the request body (BYOK) or in a
local `.env` (see `../.env.example`). Offline unit tests need neither:

```bash
python -m pytest tests/ -q     # 20 tests
ruff check .                   # same version CI pins
python security.py             # SSRF-guard self-check
```
