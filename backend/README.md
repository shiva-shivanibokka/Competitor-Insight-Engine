---
title: Competitor Intelligence Engine API
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Competitor Intelligence Engine — Backend API

FastAPI service that runs the competitor-intelligence pipeline. Deployed on
Hugging Face Spaces (Docker SDK). The [Vercel frontend](../frontend) calls it.

## Endpoints

| Method | Path         | Purpose                                            |
|--------|--------------|----------------------------------------------------|
| GET    | `/health`    | Liveness check                                     |
| GET    | `/providers` | Provider + model catalog (drives the UI dropdowns) |
| POST   | `/report`    | Run the pipeline, return the Markdown report       |

`POST /report` body:

```json
{
  "company_url": "https://stripe.com",
  "company_name": "Stripe",
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "llm_key": "<user's provider key>",
  "tavily_key": "<user's tavily key>",
  "max_competitors": 4
}
```

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
python -m pytest tests/ -q
```
