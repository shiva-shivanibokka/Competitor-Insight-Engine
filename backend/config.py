import os

from dotenv import load_dotenv

# No override=True. A real environment variable must win over a .env file:
# with override on, the placeholder ANTHROPIC_API_KEY sitting in this repo's
# .env (copied from .env.example) silently replaced a valid key already in the
# environment, and the run failed with a 401 that pointed at the key rather
# than at the file that had just overwritten it.
load_dotenv()

# All supported providers and their models.
# To add a new provider, just add a new entry here.
# Ollama runs locally — no API key needed.

# "tier" is per-provider (free / paid / local) and drives the free/paid label
# in the frontend model dropdown. "label" is the display name.
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "tier": "paid",
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        # Anthropic needs this header when called via the OpenAI-compatible wrapper
        "extra_headers": {"anthropic-version": "2023-06-01"},
        # Verified against GET /v1/models on 6 Sept 2026. claude-3-haiku-20240307
        # was in this list and had been retired — it 404'd for anyone who picked
        # it. That is what /models on the live provider is for; see app.py.
        "models": [
            "claude-sonnet-5",
            "claude-haiku-4-5",
            "claude-opus-5",
            "claude-opus-4-5",
            "claude-sonnet-4-5",
        ],
    },
    "gemini": {
        "label": "Google Gemini",
        "tier": "free",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GOOGLE_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        # Unverified — no key on hand to check these against the provider.
        # The UI replaces this list with the live one as soon as a key is
        # pasted, which is the only thing that keeps it from rotting again.
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ],
    },
    "groq": {
        "label": "Groq",
        "tier": "free",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        # Unverified, minus mixtral-8x7b-32768 which Groq decommissioned.
        # Replaced by the live list once a key is pasted.
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "tier": "paid",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        # Unverified. Replaced by the live list once a key is pasted.
        "models": [
            "gpt-4o-mini",
            "gpt-4o",
        ],
    },
    "mistral": {
        "label": "Mistral",
        "tier": "free",
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys",
        "models": [
            "mistral-large-latest",
            "mistral-small-latest",
            "open-mistral-7b",
        ],
    },
    "ollama": {
        "label": "Ollama (local)",
        "tier": "local",
        # Run `ollama serve` in a terminal before using these.
        # Pull a model first, e.g. `ollama pull phi3`
        "base_url": "http://localhost:11434/v1",
        "env_key": None,
        "models": [
            "llama3.2",
            "llama3.2:1b",
            "mistral",
            "deepseek-r1:1.5b",
            "deepseek-r1:7b",
            "phi3",
            "phi3:mini",
            "gemma3",
            "gemma3:4b",
        ],
    },
}

# Reverse lookup: given a model name, find which provider handles it
MODEL_TO_PROVIDER = {}
for provider_name, details in PROVIDERS.items():
    for model in details["models"]:
        MODEL_TO_PROVIDER[model] = provider_name

# Default models used across the pipeline.
# Change these here, or override them per-run in the notebook (Cell 3).
DEFAULT_MODEL = "claude-sonnet-5"  # used if no model is specified
FAST_MODEL = "claude-haiku-4-5"  # extraction steps — pick anything fast
SMART_MODEL = "claude-sonnet-5"  # report generation — pick anything capable

# Catch typos in the default model names at import time — before any pipeline runs
for _model in (DEFAULT_MODEL, FAST_MODEL, SMART_MODEL):
    if _model not in MODEL_TO_PROVIDER:
        raise ValueError(
            f"config.py: '{_model}' is not a recognised model. "
            f"Check the spelling or add it to the PROVIDERS dict."
        )

# Tavily key for real-time competitor search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
