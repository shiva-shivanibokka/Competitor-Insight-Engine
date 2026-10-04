# Competitor-Insight-Engine: SOP evaluation (branch `sop-eval`)

Status: **partial run.** The free Groq quota for the one model allowed here
(200,000 tokens per day) ran out before the run finished. Everything below is
measured unless it is marked as an estimate. Conditions or seeds that did not
run are listed as not run, not estimated.

## 1. Setup

| Item | Value |
|---|---|
| Code under test | `backend/` at commit `c3eac2d` (unchanged; see Change log) |
| Pipeline steps exercised | 1 scrape homepage, 2 LLM profile (gives INDUSTRY), 3 web search, 4 LLM competitor extraction. Steps 5–7 (competitor scraping/profiles, report) were **not** run. |
| LLM | `qwen/qwen3.8-27b` on the Groq free tier, `reasoning_effort="none"`, `max_tokens=700`. The product's own prompts and temperatures were used (0.0 for extraction, 0.2 for profiles). One model for every comparison. The product default (`claude-haiku-4-5`) was not used because it is paid. |
| Search | **Substituted.** The product uses Tavily, but there was no Tavily key. I used the free `ddgs` 9.13.1 metasearch (`backend=auto`) with the product's exact query string `top direct competitors of {name} in {industry}`, plus up to 6 non-blocklisted result pages fetched with the product's `scrape_page()` (600 chars each, 6,000 chars in total). `sec.gov` results were dropped. |
| Ground truth | 48 companies from SEC 10-K "Competition" sections (see §2) |
| Seeds | Seed 0 only, at temperature 0. Seeds 1–2 did **not** run because of the quota. |
| Raw outputs | `eval_sop/raw/llm_cache.jsonl` (all 188 LLM calls with prompts hashed, responses, token counts and timestamps), `raw/discovery.jsonl`, `raw/retrieval/*.json` (scraped text, profile, search text and sources) |
| Reproduce (cache replay, no API calls) | `python eval_sop/score.py` |
| Reproduce (fresh) | `EDGAR_UA="name email" python eval_sop/ground_truth/build_gt.py`, then `EVAL_GROQ_ENV=<.env> EVAL_GROQ_VAR=<var> python eval_sop/retrieve.py`, then `python eval_sop/run_discovery.py --temps 0 --seeds 0 1 2`, then `python eval_sop/score.py` |

### 2. Ground truth (`eval_sop/ground_truth/`)
- **Source.** The latest 10-K of each company on SEC EDGAR, with accession, URL and filing date in `companies.json`. Candidates came from EDGAR full-text search (phrases such as "our competitors include") plus a list of well-known tickers. All requests sent a contact User-Agent and stayed under 5 requests per second.
- **Labels are LLM-created.** Claude transcribed the competitor names in each excerpt, and Claude also added the aliases (for example Alphabet/Google/Waymo). `build_gt.py` refuses to build unless every labelled name, or an alias, occurs verbatim in the stored 10-K excerpt. All 48 passed, so every label can be checked against the filing text.
- **Fame tier.** Tiers use SEC public float (`dei:EntityPublicFloat`, XBRL frames API) as a proxy for fame: large ≥ $10B, mid $1–10B, small < $1B. There are 16 companies per tier, and the median number of ground-truth competitors is 10.5 / 6 / 6.
- **Selection was not random.** I chose companies whose 10-K names at least 3 competitors, leaning toward software and consumer companies.

### Metrics
- **Matching.** A deterministic name matcher (normalised names, legal suffixes dropped, whole-token prefix, aliases).
- **P@4.** Matched predictions among the top 4 the product would profile (`max_competitors=4`), divided by the number of predictions in the top 4. An empty output counts as 0.
- **R@4 and R@all.** Matched predictions divided by the number of ground-truth competitors.
- **Hit@4.** At least one match in the top 4.
- **CIs.** 95% percentile bootstrap over companies (10,000 resamples, seed 0). Paired differences use a paired bootstrap.
- **Simple baseline (no LLM).** The most frequent capitalised 1–3-word phrases in the same search text.

## 3. Results

### 3a. Competitor discovery, seed 0, T=0 (mean [95% CI])

| Condition | Tier | n | P@4 | R@4 | R@all | Hit@4 | Empty |
|---|---|---|---|---|---|---|---|
| (a) full pipeline | all | 48 | **0.52** [0.43, 0.62] | 0.30 [0.23, 0.39] | 0.40 [0.32, 0.49] | 0.77 [0.65, 0.90] | 0.04 |
| (a) full pipeline | large | 16 | 0.63 [0.48, 0.77] | 0.30 [0.19, 0.43] | 0.41 [0.26, 0.56] | 0.94 | 0.00 |
| (a) full pipeline | mid | 16 | 0.70 [0.56, 0.83] | 0.46 [0.32, 0.60] | 0.55 [0.40, 0.69] | 0.94 | 0.00 |
| (a) full pipeline | small | 16 | **0.25** [0.11, 0.40] | 0.15 [0.06, 0.27] | 0.25 [0.13, 0.38] | 0.44 | 0.12 |
| (b) no search, prompt as shipped ("no web search was run") | all | 48 | 0.00 | 0.00 | 0.00 | 0.00 | **1.00** |
| (b2) no search, "answer from your own knowledge" | large | 16 | 0.58 [0.42, 0.72] | 0.27 [0.17, 0.40] | 0.32 [0.20, 0.45] | 0.88 | 0.00 |
| (b2) | mid | 5 | 0.70 [0.55, 0.85] | 0.54 | 0.64 | 1.00 | 0.00 |
| (b2) | small | 0 | not run (quota) | | | | |
| (c) shuffled evidence | all | 31 | 0.03 [0.00, 0.08] | 0.01 | 0.01 | 0.06 | **0.84** |
| (d) full pipeline + fictional few-shot | all | 0 | not run (quota) | | | | |
| Simple baseline (capitalised phrases) | all | 48 | 0.10 [0.05, 0.15] | 0.06 [0.03, 0.09] | 0.13 [0.08, 0.19] | 0.29 | 0.00 |
| Simple baseline | large / mid / small | 16 each | 0.19 / 0.08 / 0.03 | | | | |

Notes on the table:
- (c) covers 16 large and 15 mid companies, and no small ones.
- (b2) covers 21 companies: the 16 large and the first 5 mid in run order.
- For (b2), the 5-company mid row is too small to interpret.

**Paired differences** (same companies, from `results/paired_diffs_T0.json`):

| Comparison | n | P@4 diff | R@all diff |
|---|---|---|---|
| (a) − (b2), large | 16 | +0.05 [−0.05, +0.14] | +0.09 [+0.03, +0.16] |
| (a) − (c) | 31 | +0.63 [+0.52, +0.73] | +0.46 [+0.34, +0.57] |
| (a) − simple baseline | 48 | +0.43 [+0.33, +0.53] | +0.27 [+0.19, +0.36] |

### 3b. Few-shot leak (Adyen / Braintree / Square in the output)
- **Not reproduced.** The original prompt produced 0 of 48 leaks in (a), 0 of 31 in (c) and 0 of 21 in (b2). A regex over all 188 raw responses found zero mentions of Adyen, Braintree or squareup.
- The Stripe demo (claude-haiku-4-5, in `frontend/public/demo/stripe.json`) does return Adyen, PayPal, Square and Braintree with the prompt's exact URLs. But those are genuine Stripe competitors, so the demo cannot tell copying apart from correct answers.
- Conclusion: with this model, the leak hypothesis is unsupported. It is untested for Haiku.

### 3c. Pipeline aborts
- 8 of 48 homepages (17%) gave no text to the product's plain-HTTP scraper: Uber, Supermicro, Wayfair, Ubiquiti, Weatherford, NETGEAR, Aviat and Phunware. That is 2 large, 3 mid and 3 small.
- `report.py` would raise `ValueError` and stop for all of them. I still scored discovery for them, using the product's fallback industry ("technology").

### 3d. Claim support of step-2 profiles (NLI judge)
- **Judge.** `cross-encoder/nli-deberta-v3-large`. A claim counts as supported if max over chunks of P(entail) ≥ 0.5. The threshold was fixed in advance and not tuned.
- **Validation on RAGTruth, not on our data.** I used 300 sentences (balanced, seed 0, 100 per task) from a local RAGTruth test copy with human span labels:
  - balanced accuracy 0.657 [0.603, 0.709]
  - Cohen's κ 0.31 [0.21, 0.42]
  - AUROC 0.71
  - The judge is only moderately reliable. No human labels from us are involved.
- **Profiles.** 40 profiles (8 aborted), 499 claims. Supported fraction, mean over companies: 0.64 [0.56, 0.71].
  - By tier: large 0.63, mid 0.59, small 0.70. The CIs overlap.
  - Claims from profiles built on < 1,000 scraped chars: 0.20 supported (n = 30 claims). From ≥ 1,000 chars: 0.67 (n = 469).
- 100 claims are exported to `results/claims_sample.csv`, with an empty `human_label` column for optional checking. No result depends on it.

## 4. What the numbers support, and what they don't

**Supported:**
- With this free model and free search, about half of the top-4 competitors the pipeline would profile are named in the company's own 10-K: P@4 0.52 [0.43, 0.62], n = 48.
- That beats a non-LLM baseline that reads the same search text: +0.43 [+0.33, +0.53].
- Quality drops sharply for small companies: P@4 0.25 vs 0.63 and 0.70.
- The extraction step depends on the evidence it is given. With another company's search text, it returns nothing 84% of the time, and P@4 falls to 0.03.
- For large-cap companies, the model's prior alone, with no retrieval, gets P@4 0.58. That is statistically indistinguishable from the full pipeline (diff +0.05 [−0.05, +0.14], n = 16). Retrieval adds recall: R@all +0.09 [+0.03, +0.16].
- When the homepage scrape is thin, profile claims are mostly unsupported by the scraped text (20% vs 67%). This matches the Duolingo demo, which drew on "public knowledge".

**Not supported:**
- The key long-tail test, prior vs retrieval for small and mid companies, **did not run** because of the quota. So "grounding matters more for the long tail" is **untested**.
- Nothing here measures the shipped configuration (claude-haiku-4-5 / claude-sonnet-5 + Tavily) or report quality (steps 5–7).
- There is no seed variance, because n_seeds = 1.
- The few-shot leak was not shown. The candidate fix (d) did not run.

## 5. Threats to validity
- **Search substitution.** ddgs is not Tavily. Its result sets and snippets differ, and they change over time. The search text is cached in `raw/retrieval/`.
- **Ground truth is incomplete and conservative.** 10-Ks list only some competitors, and some are written in legal terms. A prediction that is correct but missing from the 10-K counts as wrong, so precision is a lower bound.
- **Labels are LLM-created.** They are checked for literal presence in the excerpt, not reviewed by a human.
- **Possible ground-truth leakage into search.** Web pages can paraphrase 10-Ks. Only sec.gov was excluded.
- **Fame proxy.** Public float is not the same as LLM familiarity. For example, Herbalife is "small" by float.
- **Selection bias.** Companies were chosen because their 10-Ks name competitors.
- **Single model.** Results come from one model (qwen3.8-27b), one temperature and one seed.
- **Prior-only wording.** The outcome depends on the wording. The as-shipped wording (b) makes the model abstain every time. Only the explicit "use your own knowledge" wording (b2) measures the prior.
- **Partial conditions.** Several conditions are partial, so comparisons are paired on the companies they share.
- **NLI judge.** Its agreement with humans on RAGTruth is moderate (κ 0.31). Its support rates carry that error.
- **Third-party text in the raw data.** `raw/retrieval/*.json` contains excerpts of public web pages. Review it before pushing anywhere public.

## 6. Change log

**Product code: no changes.** `backend/` is byte-identical to `c3eac2d`.
- **Few-shot fictional-examples fix: researched, then not applied.**
  - What it was: a prompt change plus a regression test. The test failed on the original prompt (`raw/test_before_fix.txt`), and the full suite of 26 passed with the patch (`raw/test_after_fix.txt`).
  - Why it was not applied: the leak did not reproduce in the measurement (§3b). Per the "reproduce before fix" rule, the product was restored.
  - What was preserved: the patch is in `eval_sop/proposed_fewshot_fix.patch`, and the candidate prompt is in `eval_sop/fixed_prompt.py`, where it is used only by condition (d).
- **Eval-side transport shim** (`eval_sop/common.py`). It swaps only the network transport of `analyzer.llm_call` and keeps the prompts, temperatures, parsing, blocklist and dedup.

## 7. Proposed, not done
- **README test count.** The README says "22 offline unit tests" in three places (lines 207, 272 and 327). There are 25 at `c3eac2d`. Two of them need DNS, not one: `test_ssrf_allows_public` and `test_reachability_checks_do_not_follow_redirect_chains` both fail with DNS disabled (`eval_sop/check_tests_offline.py`, `raw/tests_offline.txt`). Suggested wording: "25 unit tests (23 fully offline; 2 resolve DNS)".
- **Architecture wording (for SOPs, not the README).** The pipeline is a fixed 7-step sequence. The LLM never chooses or calls a tool (`report.py`), so describe it as an LLM pipeline, not an agent. The README itself does not use the word "agent".
- **Few-shot fix.** Apply `proposed_fewshot_fix.patch` only if the leak is shown with the production model.
- **Scrape aborts.** 17% of homepages, including Uber and Wayfair, are unreadable to plain HTTP. The product could fall back to search snippets instead of aborting.

## 8. Remaining runs
- **Free, same model, after the quota resets.** Run `python eval_sop/run_discovery.py --temps 0 --seeds 0 --conds b2_prior_knowledge c_shuffled d_fixed`, then the same with `--seeds 1 2 --conds a_full b2_prior_knowledge c_shuffled d_fixed`.
  - Remaining work is about 27 b2 calls, 17 shuffled calls and 48 d calls for seed 0, plus about 384 calls for seeds 1–2.
  - That is roughly 0.7M tokens, about 4 days of the 200k/day free quota.
  - I did not move this onto local Ollama, because that would mix models within a comparison.
- **Paid, the shipped configuration (estimate, not run).**
  - Model: claude-haiku-4-5. Calls: 48 profiles + 48 × 5 conditions × 3 seeds = 768.
  - Tokens: about 1.7k in and 0.2k out per call, so about 1.3M input and 0.15M output.
  - Cost: about $2 at roughly $1/M input and $5/M output. Check current pricing before relying on this.
  - Tavily for the same run would be 48 advanced searches, 96 credits, inside its free 1,000 per month. A key is needed.

## 9. SOP-ready sentences (true as of this run)
1. "I built a 48-company ground-truth set from the Competition sections of SEC 10-K filings, stratified by public float. On it, my competitor-discovery pipeline (with an open 27B model and free web search) reached precision@4 of 0.52 (95% CI 0.43–0.62), against 0.10 for a non-LLM baseline."
2. "Precision fell from 0.63 for large-cap to 0.25 for small-cap companies. For large caps, the model's parametric knowledge alone matched the retrieval pipeline's precision within error (0.58 vs 0.63). This motivates my interest in when retrieval actually grounds LLM outputs."
3. "An evidence-shuffling ablation showed that the extraction step depends on its evidence: given another company's search results, it returned no competitors 84% of the time."
