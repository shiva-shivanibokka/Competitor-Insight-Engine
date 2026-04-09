import os
from dotenv import load_dotenv

load_dotenv(override=True)

# All supported providers and their models.
# To add a new provider, just add a new entry here.
# Ollama runs locally — no API key needed.

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GOOGLE_API_KEY",
        "models": [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
        ],
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "models": [
            "mistral-large-latest",
            "mistral-small-latest",
            "open-mistral-7b",
        ],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        # Anthropic needs this header when called via the OpenAI-compatible wrapper
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "models": [
            "claude-haiku-4-5",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-3-haiku-20240307",
        ],
    },
    "ollama": {
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
DEFAULT_MODEL = "claude-sonnet-4-5"  # used if no model is specified
FAST_MODEL = "claude-haiku-4-5"  # extraction steps — pick anything fast
SMART_MODEL = "claude-sonnet-4-5"  # report generation — pick anything capable

# Catch typos in the default model names at import time — before any pipeline runs
for _model in (DEFAULT_MODEL, FAST_MODEL, SMART_MODEL):
    if _model not in MODEL_TO_PROVIDER:
        raise ValueError(
            f"config.py: '{_model}' is not a recognised model. "
            f"Check the spelling or add it to the PROVIDERS dict."
        )

# Tavily key for real-time competitor search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
