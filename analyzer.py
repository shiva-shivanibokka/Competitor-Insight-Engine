import os
from openai import OpenAI
from config import PROVIDERS, MODEL_TO_PROVIDER, FAST_MODEL, SMART_MODEL

# -------------------------------------------------------------------
# LLM client factory — identical pattern to api_wrapper/reviewer.py
# Swap base_url to route to any provider (Groq, Gemini, OpenAI, etc.)
# -------------------------------------------------------------------


def get_client(model: str) -> OpenAI:
    """Return an OpenAI-compatible client pointed at the right provider."""
    provider_name = MODEL_TO_PROVIDER.get(model)
    if not provider_name:
        raise ValueError(
            f"Model '{model}' not found. Available models:\n"
            + "\n".join(f"  {m} (via {p})" for m, p in MODEL_TO_PROVIDER.items())
        )
    provider = PROVIDERS[provider_name]
    api_key = (
        "ollama" if provider["env_key"] is None else os.getenv(provider["env_key"])
    )
    return OpenAI(base_url=provider["base_url"], api_key=api_key)


def llm_call(
    system_prompt: str, user_prompt: str, model: str, temperature: float = 0.2
) -> str:
    """Generic LLM call — used by all three phases."""
    client = get_client(model)
    provider_name = MODEL_TO_PROVIDER[model]
    print(f"    [analyzer] {provider_name} | {model}")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content


# -------------------------------------------------------------------
# PHASE 1 — Extract a structured profile from the main company's page
# Uses the fast model (cheap + quick)
# -------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a business intelligence analyst.
Given scraped text from a company's website, extract a structured profile.

Return EXACTLY this format (no extra text before or after):

COMPANY NAME: <name>
INDUSTRY: <industry / market category>
PRODUCT OR SERVICE: <what they offer in 1-2 sentences>
TARGET CUSTOMERS: <who they sell to>
PRICING MODEL: <free / freemium / subscription / enterprise / usage-based / unknown>
KEY FEATURES: <3-5 bullet points of their main capabilities>
UNIQUE SELLING POINTS: <what they claim makes them different>
TONE & POSITIONING: <premium / budget / developer-focused / enterprise / SMB / etc.>
"""


def extract_company_profile(scraped_text: str, model: str = FAST_MODEL) -> str:
    """Phase 1: Extract a structured profile from scraped website content."""
    print("  [Phase 1] Extracting company profile...")
    return llm_call(
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_prompt=f"Extract the company profile from this website content:\n\n{scraped_text}",
        model=model,
    )


# -------------------------------------------------------------------
# PHASE 2 — Extract the same structured profile for each competitor
# Also uses the fast model — runs once per competitor
# -------------------------------------------------------------------


def extract_competitor_profile(
    competitor_name: str, scraped_text: str, model: str = FAST_MODEL
) -> str:
    """Phase 2: Extract a structured profile for a single competitor."""
    print(f"  [Phase 2] Extracting profile for: {competitor_name}")
    return llm_call(
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_prompt=f"Extract the company profile from this website content:\n\n{scraped_text}",
        model=model,
    )


# -------------------------------------------------------------------
# PHASE 3 — Generate the full competitive intelligence report
# Uses the smart model — this is the main output
# -------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """You are a senior business strategy consultant with deep expertise in competitive intelligence.

You will be given structured profiles of one main company and several of its competitors.
Your job is to produce a comprehensive, actionable Competitive Intelligence Report in Markdown.

The report must contain these five sections:

---

## 1. Company Overview
A concise summary of the main company — what they do, who they serve, and how they position themselves.

## 2. Competitor Profiles
A brief profile for each competitor — what they do, their strengths, and their positioning.

## 3. Competitive Matrix
A markdown table comparing all companies (including the main company) across these dimensions:
- Product / Service
- Target Customers
- Pricing Model
- Key Features
- Unique Selling Points
- Tone & Positioning

## 4. Market Standing
Based on the analysis, rank and describe where each company stands in the market.
Identify who leads on: features, pricing, brand, target market reach.

## 5. Strategic Recommendations
Give 5-7 specific, actionable recommendations for the main company to strengthen its market position.
Each recommendation should reference a specific gap or weakness identified in the analysis.

---

Be direct, specific, and insightful. Avoid vague generalities. Format everything cleanly in Markdown.
"""


def generate_intelligence_report(
    company_name: str,
    main_profile: str,
    competitor_profiles: list[dict],
    model: str = SMART_MODEL,
) -> str:
    """
    Phase 3: Generate the full competitive intelligence report.

    competitor_profiles: list of {"name": str, "url": str, "profile": str}
    """
    print("  [Phase 3] Generating full intelligence report...")

    # Build the user prompt by assembling all profiles
    competitors_text = ""
    for i, comp in enumerate(competitor_profiles, 1):
        competitors_text += (
            f"\n\n--- COMPETITOR {i}: {comp['name']} ({comp['url']}) ---\n"
        )
        competitors_text += comp["profile"]

    user_prompt = (
        f"MAIN COMPANY: {company_name}\n\n"
        f"--- MAIN COMPANY PROFILE ---\n{main_profile}"
        f"\n\n{'=' * 60}\n"
        f"COMPETITOR PROFILES:{competitors_text}"
        f"\n\n{'=' * 60}\n\n"
        f"Now generate the full Competitive Intelligence Report for {company_name}."
    )

    return llm_call(
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
        temperature=0.3,
    )
