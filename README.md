# Competitor Intelligence Report Generator

Give this tool any company's website URL and it automatically produces a full competitive intelligence report — including a side-by-side comparison of competitors, market positioning analysis, and strategic recommendations.

---

## What It Does

Most competitive research is done manually: open ten browser tabs, read through each company's website, take notes, build a comparison table. This tool does all of that automatically using AI.

You input one URL. The tool outputs a structured business report in under 90 seconds.

---

## How It Works

The pipeline has seven steps:

**Step 1 — Validate and scrape the main company**
Before scraping begins, the tool checks that the URL is actually reachable and returns a valid response. If the URL is wrong or the site is down, it stops immediately with a clear error message rather than failing silently later. It then makes an HTTP request to the company's homepage and key sub-pages (about, product, pricing, careers) using the `requests` library, and uses `BeautifulSoup` to parse the HTML, strip out noise (scripts, ads, navigation), and extract only the readable text.

**Step 2 — Extract a company profile (LLM Call 1)**
A fast, lightweight language model reads the scraped text and pulls out structured signals: what the company does, who they serve, how they price, and what makes them different. This project uses **Claude (`claude-haiku-4-5`)** for this step — Anthropic's fastest model, designed for high-throughput tasks that require speed over depth. The industry extracted here is also used to make the competitor search query more precise.

**Step 3 — Find competitors in real time (Tavily)**
The tool uses the Tavily Search API to search for the top competitors of this company right now — not from a static list, but from a live web search based on the company's name and industry. It retrieves the full text content of up to 10 search results, which is then passed to the next step rather than using the URLs directly. This is important: search results are pages *about* competitors (articles, listicles, Reddit threads) — not the competitor companies themselves.

**Step 4 — Filter, validate, and rank competitors (LLM Call 2)**
This is the most important quality step in the pipeline. The raw search content from Step 3 is fed to the LLM with a strict prompt that instructs it to identify only actual direct competitor companies and rank them from most relevant to least relevant. The LLM is explicitly told to never return Reddit, Wikipedia, Quora, news sites, review sites, or any non-company URL.

After the LLM responds, a second layer of hard-coded validation runs — a blacklist of domains (Reddit, Forbes, G2, Capterra, LinkedIn, and 20+ others) that are permanently rejected regardless of what the LLM says. This two-layer approach — LLM filtering followed by code validation — is what ensures only real, relevant competitors make it through.

The user's `max_competitors` setting then takes the top N from the ranked list, so the most relevant competitors are always chosen first.

**Step 5 — Validate and scrape each competitor**
Each competitor URL is checked for reachability before scraping begins. If a URL returns a 404, redirects to a login page, or times out, that competitor is skipped gracefully and the pipeline continues with the remaining ones. The same scraping logic from Step 1 is applied to each valid competitor site.

**Step 6 — Extract competitor profiles (LLM Call 3)**
`claude-haiku-4-5` runs once per competitor, extracting the same structured profile fields from each competitor's scraped content. The model is reused intentionally: consistency in the extraction format is what makes the side-by-side comparison in the final report accurate and meaningful.

**Step 7 — Generate the full report (LLM Call 4)**
**Claude (`claude-sonnet-4-5`)** takes all the profiles — the main company and all competitors — and generates the full report. Sonnet sits between Haiku and Opus: capable enough to synthesise multiple inputs, spot competitive patterns, and produce strategic recommendations, without the cost of the most powerful model. This is where the depth of Claude's reasoning is most visible in the output.

---

## The Report

The final output is a clean, readable Markdown report with five sections:

1. **Company Overview** — what the company does and how it positions itself
2. **Competitor Profiles** — a summary of each competitor
3. **Competitive Matrix** — a side-by-side table comparing all companies on product, pricing, target customers, features, and positioning
4. **Market Standing** — who leads on what, and where each company is strong or weak
5. **Strategic Recommendations** — 5–7 specific, actionable things the main company can do to strengthen its position

---

## Models Used

This project uses **Anthropic Claude** as the default LLM for all pipeline steps.

| Step | Model | Why |
|------|-------|-----|
| Extraction (LLM Calls 1, 2, 3) | `claude-haiku-4-5` | Anthropic's fastest model — ideal for structured extraction tasks |
| Report generation (LLM Call 4) | `claude-sonnet-4-5` | Strong reasoning and writing — produces detailed, insightful reports |

Claude was chosen for this project because of its strong instruction-following (critical for structured JSON output in the competitor filtering step) and its ability to produce well-reasoned, readable business writing in the final report.

---

## Use Any AI Model

The project is built on a flexible API wrapper — you are not locked into Claude. All LLM calls are made using the **OpenAI Python SDK** as a universal client. Every supported provider exposes an OpenAI-compatible REST API, so the same `client.chat.completions.create()` call works across all six providers — only the `base_url` and `api_key` change. No provider-specific SDK is needed; switching models requires no code changes.

To switch providers, change the model name in one of these two places:

- **For a single run:** update `FAST_MODEL_OVERRIDE` and `SMART_MODEL_OVERRIDE` in `competitor_intel.ipynb` Cell 3
- **To change the default permanently:** update `FAST_MODEL` (line 88) and `SMART_MODEL` (line 89) in `config.py`

Pick any model name from the table below — the wrapper automatically routes it to the right provider.

| Provider | Example Models | Cost |
|----------|---------------|------|
| **Anthropic (default)** | `claude-haiku-4-5`, `claude-sonnet-4-5`, `claude-opus-4-5` | Paid |
| Groq | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `gemma2-9b-it` | Free |
| Google Gemini | `gemini-2.0-flash`, `gemini-1.5-pro` | Free |
| OpenAI | `gpt-4o`, `gpt-4o-mini` | Paid |
| Mistral | `mistral-large-latest`, `open-mistral-7b` | Free tier |
| Ollama (local) | `llama3.2`, `phi3`, `gemma3`, `deepseek-r1` | Free (runs on your machine) |

---

## Project Structure

```
competitor_intelligence/
├── competitor_intel.ipynb  # Start here — configure and run the tool
├── report.py               # Runs the full pipeline from start to finish
├── analyzer.py             # All LLM calls — extraction and report generation
├── searcher.py             # Tavily search — finds competitors in real time
├── scraper.py              # Web scraper — fetches and cleans website content
├── config.py               # All providers, models, and default settings
├── requirements.txt        # Python dependencies
├── .env                    # API keys (not committed to git)
└── .gitignore
```

### What Each File Does

**`competitor_intel.ipynb`**
This is the only file you need to open. It is a Jupyter notebook with six cells. You set your company URL, name, and model choice in Cell 3, then run all cells in order. The report is displayed in Cell 5 and can optionally be saved to a `.md` file in Cell 6.

**`report.py`**
This is the brain of the project. It runs the full seven-step pipeline in the correct order — validate the URL, scrape, extract, search, filter, scrape competitors, profile them, generate the report. It also handles all the error checking between steps: if something goes wrong at any point, it stops cleanly with a helpful message instead of crashing with a raw error.

**`analyzer.py`**
This file contains all four LLM calls in the project. It handles routing to the correct AI provider, sending prompts, receiving responses, and validating that the responses are usable. It also contains the system prompts that tell the LLM what to extract and how to write the report.

**`searcher.py`**
This file talks to the Tavily Search API. It builds a search query using the company name and industry, retrieves up to 10 search results, and returns the raw text content of those results. It also contains a blacklist of sites (Reddit, Wikipedia, news sites, review platforms) that are filtered out before the content is even passed to the LLM.

**`scraper.py`**
This file fetches web pages. Given a URL, it makes an HTTP request, parses the HTML using BeautifulSoup, strips out everything that is not useful (scripts, ads, navigation bars, footers), and returns clean readable text. It tries the homepage first, then common sub-pages like `/about`, `/product`, and `/pricing`.

**`config.py`**
This file is the central settings file for the project. It lists every supported AI provider (Anthropic, Groq, Gemini, OpenAI, Mistral, Ollama) along with their API endpoints, environment variable names, and available model names. It also sets the default models used across the pipeline. If you want to change which model the project uses permanently, this is the file to edit.

**`.env`**
This file stores your API keys. It is never committed to git. You need at minimum `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` to run the project with the default settings.

**`requirements.txt`**
Lists the Python packages needed to run the project. Install them all at once with `pip install -r requirements.txt`.

---

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Add your API keys to `.env`**
```
ANTHROPIC_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here
```
Get an Anthropic API key at [console.anthropic.com](https://console.anthropic.com)  
Get a free Tavily key at [app.tavily.com](https://app.tavily.com)  
Optional — get a free Groq key at [console.groq.com](https://console.groq.com) if you want a free alternative

**3. Open the notebook**
```bash
jupyter notebook competitor_intel.ipynb
```

**4. Set your target company and run**
```python
COMPANY_URL  = "https://www.stripe.com"
COMPANY_NAME = "Stripe"
```

---

## Guardrails and Edge Cases

A lot of things can go wrong when you combine web scraping, a search API, and multiple LLM calls. The pipeline is built to handle failures at every step — it never crashes silently, and every error message tells you exactly what went wrong and what to do about it.

### Input Validation (before anything runs)

| Situation | What Happens |
|-----------|-------------|
| `company_url` is empty or not a string | Raises an error immediately with an example of the correct format |
| `company_name` is empty or not a string | Raises an error immediately |
| `max_competitors` is set to 0 or less | Raises an error — must be at least 1 |
| URL is missing `https://` (e.g. `stripe.com`) | Automatically prepends `https://` and logs a warning — no need to re-run |

### Scraping Guardrails

| Situation | What Happens |
|-----------|-------------|
| Main company URL is unreachable or returns an error | Stops immediately with a message listing what to check |
| Main company page scrapes successfully but returns very little text | Warns that profile quality may be low and continues |
| Main company page returns no text at all (JavaScript-heavy site) | Stops and suggests trying a specific sub-page like `/about` |
| A competitor URL has no `https://` scheme | Logged and skipped — never passed to the scraper |
| A competitor URL is unreachable | Skipped with a log message — pipeline continues with remaining competitors |
| A competitor page returns no readable text | Skipped with a log message — pipeline continues |
| A competitor page returns very little text | Warns that profile quality may be low and continues |

### LLM and Search Guardrails

| Situation | What Happens |
|-----------|-------------|
| Tavily API call fails (network error, rate limit, bad key) | Raises a clear error naming the likely cause and what to check |
| Tavily returns fewer than 3 results | Warns that competitor identification may be limited |
| Tavily returns no results at all | Raises an error with instructions to check the API key |
| LLM returns a site like Reddit, Wikipedia, or Forbes as a competitor | Stripped from search content before the LLM even sees it (Layer 1) |
| LLM still returns a blacklisted site despite instructions | Hard-coded blacklist rejects it after the LLM responds (Layer 2) |
| LLM returns the same competitor twice under different names | Deduplicated by domain — only the first occurrence is kept |
| LLM returns malformed or non-JSON output | Caught, logged with the raw output for debugging, returns empty list |
| LLM returns a profile where most fields are "unknown" | Warns that the scraped page was likely a bot-detection wall or login screen |
| API key for the chosen provider is missing from `.env` | Raises an error immediately naming the exact environment variable to set |
| LLM call fails due to a network or authentication error | Raises a clear error with the provider name, model, and what to check |
| The model name set in `config.py` does not exist | Caught at import time — fails immediately before any pipeline runs |

### Report Guardrails

| Situation | What Happens |
|-----------|-------------|
| All competitor websites fail to scrape | Raises an error suggesting to try again |
| Fewer competitors profiled than requested | Warning is printed — report is still generated with what was found |
| Only 1 competitor was successfully profiled | Warns that comparisons in the report may be limited |
| Main company profile comes back empty | Raises an error before wasting API calls on the search and competitors |
| Report generation returns an empty response | Raises an error suggesting to try again or switch to a different model |

### Why Two Layers of Competitor Filtering?

Relying solely on the LLM to filter competitors is not enough — language models can still return unexpected results. The pipeline uses two independent layers:

1. **Before the LLM**: blacklisted domains are stripped from the Tavily search content so the LLM never even sees them (`searcher.py`)
2. **After the LLM**: every URL the LLM returns is checked against the same blacklist in code — a hard rejection that cannot be overridden by the model (`analyzer.py`)

This means a site like Reddit would have to get past both layers independently to appear in the report — which is not possible.

---

## Key Concepts Demonstrated

- **Multi-step LLM pipelines** — using different models for different tasks (fast model for extraction, strong model for generation)
- **Real-time web search** with the Tavily API
- **Web scraping** with `requests` and `BeautifulSoup`
- **Provider-agnostic LLM calls** — one wrapper, six providers, zero code changes to switch
- **Prompt engineering** — structured extraction prompts, ranking instructions, and strict output constraints
- **Chaining outputs** — the output of one LLM call becomes the input of the next
- **Defensive pipeline design** — input validation, output validation, graceful degradation, and informative error messages at every step
