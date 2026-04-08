import os
from dotenv import load_dotenv

load_dotenv(override=True)

# -------------------------------------------------------------------
# Provider registry
# Each provider needs a base_url, an api_key, and a list of models.
# Ollama is local — no real key needed, models run on your machine.
# -------------------------------------------------------------------

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
        "models": [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-3-5",
        ],
    },
    "ollama": {
        # Ollama runs on your machine — no key needed, no API cost
        # To use: run `ollama serve` in your terminal first
        # Then pull whichever model you want: e.g. `ollama pull phi3`
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

# Build a quick lookup: model name -> which provider handles it
MODEL_TO_PROVIDER = {}
for provider_name, details in PROVIDERS.items():
    for model in details["models"]:
        MODEL_TO_PROVIDER[model] = provider_name

# -------------------------------------------------------------------
# Defaults
# FAST_MODEL  : used for LLM 1 and LLM 2 (extraction — cheap, quick)
# SMART_MODEL : used for LLM 3 (full report generation — more capable)
# -------------------------------------------------------------------
DEFAULT_MODEL = "llama-3.3-70b-versatile"  # fallback if user picks nothing
FAST_MODEL = "llama-3.1-8b-instant"  # Groq — free and very fast
SMART_MODEL = "llama-3.3-70b-versatile"  # Groq — free and strong

# Tavily API key for real-time competitor search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
