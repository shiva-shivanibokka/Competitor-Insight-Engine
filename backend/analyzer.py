import json
import os
import re
from urllib.parse import urlparse

from openai import BadRequestError, OpenAI

from blocklist import is_blocked
from config import FAST_MODEL, MODEL_TO_PROVIDER, PROVIDERS, SMART_MODEL

# BYOK: keys arrive per-request as {provider_name: key} and are used in-memory only.
# They are NEVER written to disk, logged, or echoed back. Do not print this dict.
ApiKeys = dict[str, str]


def get_client(model: str, api_keys: ApiKeys | None = None) -> OpenAI:
    """Look up the provider for this model and return a configured client."""
    provider_name = MODEL_TO_PROVIDER.get(model)
    if not provider_name:
        raise ValueError(
            f"Model '{model}' not found. Available models:\n"
            + "\n".join(f"  {m} (via {p})" for m, p in MODEL_TO_PROVIDER.items())
        )
    return client_for(provider_name, api_keys)


def client_for(provider_name: str, api_keys: ApiKeys | None = None) -> OpenAI:
    """Configured client for a provider.

    Key resolution order: per-request BYOK dict → environment variable (local/CLI).
    """
    api_keys = api_keys or {}
    provider = PROVIDERS[provider_name]
    if provider["env_key"] is None:
        api_key = "ollama"  # local, no key needed
    else:
        api_key = api_keys.get(provider_name) or os.getenv(provider["env_key"])
        if not api_key:
            raise ValueError(
                f"No API key provided for '{provider_name}'. "
                f"Enter your {provider_name} key in the app (BYOK), "
                f"or set {provider['env_key']} in .env for local use."
            )
    # Some providers need extra headers (e.g. Anthropic needs anthropic-version)
    extra_headers = provider.get("extra_headers", {})
    return OpenAI(
        base_url=provider["base_url"],
        api_key=api_key,
        default_headers=extra_headers,
    )


def list_models(provider_name: str, api_key: str) -> list[str]:
    """The models this key can actually use, straight from the provider.

    config.py's catalogue is a starting point, not the truth. A hardcoded list
    goes stale in silence: this one shipped `claude-3-haiku-20240307` long after
    it was retired, so the dropdown offered a model that 404'd on selection.
    Every provider here speaks the OpenAI-compatible /v1/models, so one call
    covers all of them.
    """
    client = client_for(provider_name, {provider_name: api_key})
    return sorted(m.id for m in client.models.list().data)


# Models that reject `temperature` outright. Newer Anthropic models return
# 400 `temperature is deprecated for this model`, which turns a working app
# into one that 500s the moment a current model is added to the catalogue.
#
# Learned at runtime instead of hardcoded on purpose: a hand-maintained list of
# per-model quirks rots exactly the way the model catalogue itself rots, and
# providers ship models faster than this file gets edited. One wasted call per
# model per process buys a rule that stays true without anyone updating it.
_REJECTS_TEMPERATURE: set[str] = set()


def llm_call(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    api_keys: ApiKeys | None = None,
) -> str:
    """Send a prompt to the model and return the response text."""
    client = get_client(model, api_keys)
    provider_name = MODEL_TO_PROVIDER[model]
    print(f"    [llm] {provider_name} | {model}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    def create(**extra):
        return client.chat.completions.create(model=model, messages=messages, **extra)

    try:
        if model in _REJECTS_TEMPERATURE:
            response = create()
        else:
            try:
                response = create(temperature=temperature)
            except BadRequestError as e:
                if "temperature" not in str(e):
                    raise
                _REJECTS_TEMPERATURE.add(model)
                print(f"    [llm] {model} rejects temperature — retrying without it")
                response = create()
        return response.choices[0].message.content or ""
    except Exception as e:
        # ValueError so the API answers 422: a rejected key, an unavailable
        # model or a rate limit is something the caller can act on, not a fault
        # in this service.
        raise ValueError(
            f"LLM call failed ({provider_name} | {model}): {e}\n"
            f"Check that your {provider_name} key is valid and the model name is current."
        ) from e


# ------------------------------------------------------------------
# Competitor extraction
# Reads raw Tavily search content, returns a ranked list of actual
# competitor companies — filters out blogs, news, review sites, etc.
# ------------------------------------------------------------------

COMPETITOR_EXTRACTION_PROMPT = """You are a business intelligence analyst
specialising in competitive research.

You will be given search result content about competitors of a specific company.
Your job is to identify the ACTUAL direct competitor companies and rank them by relevance.

A direct competitor is a company that:
- Sells a similar product or service
- Targets the same customer segment
- Operates in the same industry

STRICT RULES — violation means the entire output is wrong:
1. Only include COMPANIES — not websites, forums, publications, or platforms
2. NEVER include: Reddit, Quora, Wikipedia, LinkedIn, YouTube, Medium, Forbes, TechCrunch,
   G2, Capterra, Trustpilot, Glassdoor, Crunchbase, ProductHunt, or any review/news/social site
3. Each URL must be the company's official homepage (e.g. https://www.adyen.com)
4. Do NOT include the company being researched itself
5. Rank competitors from most relevant (most similar product + market) to least relevant
6. Return ONLY a valid JSON array — no explanation, no markdown, no extra text

Output format:
[
  {"name": "Adyen", "url": "https://www.adyen.com"},
  {"name": "Braintree", "url": "https://www.braintreepayments.com"},
  {"name": "Square", "url": "https://www.squareup.com"}
]
"""

def _is_valid_competitor_url(url: str, company_name: str) -> bool:
    """Returns False if the URL is blocklisted or belongs to the main company."""
    if not url.startswith(("http://", "https://")):
        return False
    if is_blocked(url):  # shared blocklist — see blocklist.py
        return False
    # Match the company name against whole host labels, not as a substring of
    # the URL. Substring matching made short names reject unrelated companies:
    # researching "Ada" threw away adaptive.com, "Wise" threw away wisetech.com.
    # Labels rather than just the second level so a company's own subdomain
    # (dashboard.stripe.com) is still recognised as the company.
    host = (urlparse(url).hostname or "").lower()
    return company_name.lower().replace(" ", "") not in host.split(".")[:-1]


def extract_competitors_from_search(
    company_name: str,
    search_content: str,
    model: str = FAST_MODEL,
    api_keys: ApiKeys | None = None,
) -> list[dict]:
    """
    Feed raw Tavily search results to the LLM.
    Returns a clean ranked list of real competitor companies.
    Any junk that slips past the LLM is caught by the hard blacklist.
    """
    print("  [step] Extracting and ranking real competitors from search results...")
    raw = llm_call(
        system_prompt=COMPETITOR_EXTRACTION_PROMPT,
        user_prompt=(
            f"The company being researched is: {company_name}\n\n"
            f"Search results:\n\n{search_content}"
        ),
        model=model,
        temperature=0.0,  # keep this at zero — we want consistent, factual output
        api_keys=api_keys,
    )

    # Strip markdown fences if the model wrapped the JSON
    try:
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()  # type: ignore[arg-type]
        competitors = json.loads(cleaned)
    except Exception as e:  # noqa: BLE001 - LLM output is untrusted; degrade, never crash
        print(f"  [!] Could not parse response: {e}\n  Output was:\n{raw[:400]}")
        return []

    if not isinstance(competitors, list):
        print(f"  [!] Unexpected response format: {type(competitors)}")
        return []

    # Run every result through the hard blacklist and deduplicate by domain
    validated = []
    seen_domains = set()
    for c in competitors:
        if not isinstance(c, dict):  # LLM sometimes returns bare strings, not objects
            print(f"  [!] Skipped non-object entry: {c!r}")
            continue
        name = c.get("name", "").strip()
        url = c.get("url", "").strip()
        if not name or not url:
            continue
        if not _is_valid_competitor_url(url, company_name):
            print(f"  [!] Removed: {name} ({url})")
            continue
        # Normalise domain for deduplication (strip www., lowercase)
        domain = re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")
        if domain in seen_domains:
            print(f"  [!] Duplicate skipped: {name} ({url})")
            continue
        seen_domains.add(domain)
        validated.append({"name": name, "url": url})

    print(f"  [step] {len(validated)} competitor(s) passed validation.")
    return validated  # already ranked most-relevant first by the LLM


# ------------------------------------------------------------------
# Company profile extraction
# Same prompt runs for the main company and each competitor —
# consistent format is what makes the final comparison work
# ------------------------------------------------------------------

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


def _warn_if_low_quality(profile: str, name: str) -> None:
    """Warn if the profile looks like it was extracted from a near-empty page."""
    unknown_count = profile.lower().count("unknown")
    if unknown_count >= 5:
        print(
            f"  [!] Warning: profile for '{name}' has {unknown_count} 'unknown' fields. "
            f"The scraped page may have been a bot-detection wall or login screen."
        )


def extract_company_profile(
    scraped_text: str, model: str = FAST_MODEL, api_keys: ApiKeys | None = None
) -> str:
    """Extract a structured profile from the main company's scraped content."""
    print("  [step] Extracting company profile...")
    profile = llm_call(
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_prompt=f"Extract the company profile from this website content:\n\n{scraped_text}",
        model=model,
        api_keys=api_keys,
    )
    if not profile.strip():
        raise ValueError(
            "Got an empty profile for the main company. Check the URL and try again."
        )
    _warn_if_low_quality(profile, "main company")
    return profile


def extract_competitor_profile(
    competitor_name: str,
    scraped_text: str,
    model: str = FAST_MODEL,
    api_keys: ApiKeys | None = None,
) -> str:
    """Extract a structured profile for a single competitor."""
    print(f"  [step] Extracting profile for: {competitor_name}")
    profile = llm_call(
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_prompt=(
            f"Extract the company profile for {competitor_name} "
            f"from this website content:\n\n{scraped_text}"
        ),
        model=model,
        api_keys=api_keys,
    )
    _warn_if_low_quality(profile, competitor_name)
    return profile


# ------------------------------------------------------------------
# Report generation
# Takes all profiles and produces the full intelligence report.
# Change SMART_MODEL in config.py or pass a different model here.
# ------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """You are a senior business strategy consultant with
deep expertise in competitive intelligence.

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
    api_keys: ApiKeys | None = None,
) -> str:
    """Generate the full competitive intelligence report from all collected profiles."""
    print("  [step] Generating full intelligence report...")

    if len(competitor_profiles) < 2:
        print(
            f"  [!] Warning: only {len(competitor_profiles)} competitor(s) available — "
            f"comparisons in the report may be limited."
        )

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

    report = llm_call(
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
        api_keys=api_keys,
        temperature=0.3,
    )
    if not report.strip():
        raise ValueError(
            "Report generation returned an empty response. Try again or switch to a different model."
        )
    return report
