# Competitor Intelligence Report Generator

Give this tool any company's website URL and it automatically produces a full competitive intelligence report — including a side-by-side comparison of competitors, market positioning analysis, and strategic recommendations.

---

## What It Does

Most competitive research is done manually: open ten browser tabs, read through each company's website, take notes, build a comparison table. This tool does all of that automatically using AI.

You input one URL. The tool outputs a structured business report in under 90 seconds.

---

## How It Works

The pipeline has six steps:

**Step 1 — Scrape the main company**
The tool makes an HTTP request to the company's homepage and key sub-pages (about, product, pricing, careers) using the `requests` library. It then uses `BeautifulSoup` to parse the HTML, strip out noise (scripts, ads, navigation), and extract only the readable text.

**Step 2 — Extract a company profile (LLM Call 1)**
A fast, lightweight language model reads the scraped text and pulls out structured signals: what the company does, who they serve, how they price, and what makes them different. "Fast" here means a smaller model — such as `llama-3.1-8b-instant` via Groq — that responds in under a second and costs almost nothing per call. We use it here because this is a straightforward extraction task that does not need a more powerful model.

**Step 3 — Find competitors in real time (Tavily)**
The tool uses the Tavily Search API to find the top competitors of this company right now — not from a static list, but from a live web search based on the company's name and industry.

**Step 4 — Scrape each competitor**
The same scraping process from Step 1 runs for every competitor found — same library, same logic, just a different URL each time.

**Step 5 — Extract competitor profiles (LLM Call 2)**
The same fast model from Step 2 runs again — once per competitor — extracting the same structured profile from each competitor's scraped content. It is called "LLM 2" not because it is a different model, but because it is a separate call in the pipeline with a different input. The model is reused intentionally: consistency in the extraction format is what makes the final comparison possible.

**Step 6 — Generate the full report (LLM Call 3)**
A more capable language model takes all the profiles — the main company and all competitors — and generates a comprehensive report with five sections (see below). This is where a stronger model earns its place: synthesising multiple inputs, spotting patterns, and producing strategic recommendations requires deeper reasoning than simple extraction.

---

## The Report

The final output is a clean, readable Markdown report with five sections:

1. **Company Overview** — what the company does and how it positions itself
2. **Competitor Profiles** — a summary of each competitor
3. **Competitive Matrix** — a side-by-side table comparing all companies on product, pricing, target customers, features, and positioning
4. **Market Standing** — who leads on what, and where each company is strong or weak
5. **Strategic Recommendations** — 5–7 specific, actionable things the main company can do to strengthen its position

---

## Use Any AI Model

This project is built on a flexible API wrapper that supports multiple AI providers. You change one line — the model name — and the tool routes to the right provider automatically.

| Provider | Example Models | Cost |
|----------|---------------|------|
| Groq | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `gemma2-9b-it` | Free |
| Google Gemini | `gemini-2.0-flash`, `gemini-1.5-pro` | Free |
| Anthropic | `claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-3-5` | Paid |
| OpenAI | `gpt-4o`, `gpt-4o-mini` | Paid |
| Mistral | `mistral-large-latest`, `open-mistral-7b` | Free tier |
| Ollama (local) | `llama3.2`, `phi3`, `gemma3`, `deepseek-r1` | Free (runs on your machine) |

The default setup uses **Groq** — fully free, no credit card needed.

---

## Project Structure

```
competitor_intelligence/
├── competitor_intel.ipynb  # Start here — configure and run the tool
├── report.py               # Orchestrates the full pipeline
├── analyzer.py             # All LLM calls (extraction + report generation)
├── searcher.py             # Tavily search — finds competitor URLs in real time
├── scraper.py              # Web scraper — fetches and cleans website content
├── config.py               # Provider registry and model routing
├── .env                    # API keys (not committed to git)
└── .gitignore
```

---

## Setup

**1. Install dependencies**
```bash
pip install requests beautifulsoup4 openai python-dotenv tavily-python
```

**2. Add your API keys to `.env`**
```
GROQ_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here
```
Get a free Groq key at [console.groq.com](https://console.groq.com)  
Get a free Tavily key at [app.tavily.com](https://app.tavily.com)

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

## Key Concepts Demonstrated

- **Multi-step LLM pipelines** — using different models for different tasks (fast model for extraction, strong model for generation)
- **Real-time web search** with the Tavily API
- **Web scraping** with `requests` and `BeautifulSoup`
- **Provider-agnostic LLM calls** — one wrapper, five providers, zero code changes to switch
- **Prompt engineering** — structured extraction prompts and report generation prompts
- **Chaining outputs** — the output of one LLM call becomes the input of the next
