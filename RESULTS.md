# Competitor-Insight-Engine: SOP evaluation (branch `sop-eval`)

**Status: partial run (Groq, seed 0) plus a fix phase.** The free Groq quota (200,000 tokens a day for the one allowed model) ran out before every condition finished. After an adversarial review, the harness was fixed so a paid Haiku run can be done under a hard cost cap. That paid run has **not** been done.

Every number below is measured unless it says otherwise. Anything that did not run is marked as not run; nothing missing has been estimated.

## 1. Setup

| Item | Value |
|---|---|
| Code under test | `backend/` at commit `c3eac2d`. Unchanged; see the Change log. |
| Pipeline steps exercised | Step 1 scrapes the homepage. Step 2 builds an LLM profile, which supplies INDUSTRY. Step 3 runs a web search. Step 4 is LLM competitor extraction. Steps 5–7 (competitor profiles and the report) were **not run**. |
| LLM (the only model in every reported comparison) | `qwen/qwen3.8-27b` on the Groq free tier, with `reasoning_effort="none"` and `max_tokens=700`. The product's own prompts and temperatures were used: 0.0 for extraction and 0.2 for the profile. |
| Search | **Substituted, so this is not the shipped configuration.** No Tavily key was available. I used free `ddgs` 9.13.1 metasearch (`backend=auto`) with the product's exact query `top direct competitors of {name} in {industry}`. On top of the snippets, up to 6 non-blocklisted result pages were fetched with the product's `scrape_page()`, at 600 characters each and 6,000 characters in total. sec.gov results were dropped. All search text is cached in `raw/retrieval/`. |
| Ground truth | 48 companies from SEC 10-K "Competition" sections (see §2). |
| Runs | One run at temperature 0, seed 0. Seeds 1–2 were not run because of the quota. |
| Raw outputs | `raw/llm_cache.jsonl` holds all 188 LLM calls (hashed prompts, responses, token counts, timestamps). Also `raw/discovery.jsonl` and `raw/retrieval/*.json`. |
| Replay (no API calls) | `python eval_sop/score.py && python eval_sop/sensitivity.py`. `tests/test_transport.py` checks that all 148 discovery records replay exactly from the cache. |
| Fresh run | `EDGAR_UA="Competitor-Insight-Engine noreply@users.noreply.github.com" python eval_sop/ground_truth/build_gt.py` (SEC asks for a contact in the User-Agent; use a no-reply address, not a personal one), then `retrieve.py`, `run_discovery.py` and `score.py`. Set the key with `EVAL_KEY_ENV` / `EVAL_KEY_VAR`. |

### 2. Ground truth (`eval_sop/ground_truth/`)
- **Source.** Each company's latest 10-K on EDGAR; accession, URL and filing date are in `companies.json`.
- **How the labels were made.** The labels are **LLM-assisted**: Claude transcribed the competitor names from each excerpt and added aliases. `build_gt.py` refuses to write `companies.json` (SystemExit) unless every labelled entity has its name, or one of its aliases, appearing verbatim in the stored 10-K excerpt. That refusal was added in `cc9d581`; before it, problems were only printed. All 48 companies pass. Labels have not been reviewed by a human.
- **Coverage scope.** A label set covers the named competitors in one stored passage, which is not necessarily the whole filing. For example, NETGEAR's set covers its enterprise bullet only.
- **Fame tier.** Public float from SEC XBRL `dei:EntityPublicFloat`, used as a proxy for fame: large ≥ $10B, mid $1–10B, small < $1B. There are 16 companies per tier.
- **Selection.** Companies were selected for naming at least 3 competitors in the filing, so this is not a random sample.

### Metrics
- **P@4.** Of the top 4 predictions the product would profile (`max_competitors=4`), the share that match a ground-truth entity. The denominator is the number of predictions in the top 4. An empty output counts as 0.
- **R@4 and R@all.** Matched entities divided by the number of ground-truth entities, using the top 4 or the whole list.
- **Hit@4.** Whether at least one ground-truth entity appears in the top 4.
- **Matching.** Deterministic name matching with normalisation and whole-token prefix matching.
- **Confidence intervals.** 95% percentile bootstrap over companies, 10,000 resamples, seed 0. Comparisons between conditions use a paired bootstrap.
- **Simple baseline (no LLM).** The most frequent capitalised 1–3-word phrases in the same search text.

## 3. Results (`qwen/qwen3.8-27b`, temperature 0, single run)

### 3a. Competitor discovery: mean [95% CI]

| Condition | Tier | n | P@4 | P@4, verbatim-only labels | R@all | Hit@4 | Empty |
|---|---|---|---|---|---|---|---|
| (a) full pipeline | all | 48 | **0.53** [0.43, 0.62] | 0.48 [0.39, 0.58] | 0.39 [0.31, 0.48] | 0.79 | 0.04 |
| (a) | large | 16 | 0.63 [0.48, 0.77] | 0.53 [0.38, 0.69] | 0.40 | 0.94 | 0 |
| (a) | mid | 16 | 0.70 [0.56, 0.83] | 0.66 [0.50, 0.78] | 0.53 | 0.94 | 0 |
| (a) | small | 16 | **0.26** [0.12, 0.41] | 0.26 [0.13, 0.41] | 0.25 | 0.50 | 0.12 |
| (b) no search, as-shipped wording ("no web search was run") | all | 48 | 0.00 | 0.00 | 0.00 | 0.00 | **1.00** |
| (b2) no search, "answer from your own knowledge" (**post hoc**) | large | 16 | 0.59 [0.44, 0.73] | 0.50 [0.34, 0.64] | 0.32 | 0.88 | 0 |
| (b2) | mid | 5 | 0.70 | 0.60 | 0.59 | 1.00 | 0 |
| (b2) | small | 0 | not run (quota) | | | | |
| (c) shuffled evidence (another company's search text) | large + mid | 31 | 0.03 [0.00, 0.08] | 0.02 | 0.01 | 0.06 | **0.84** |
| (d) fixed few-shot prompt | all | 0 | not run (quota) | | | | |
| Simple baseline | all | 48 | 0.10 [0.05, 0.15] | — | 0.13 | 0.29 | 0 |
| Simple baseline | large / mid / small | 16 each | 0.19 / 0.08 / 0.03 | — | | | |

**Paired differences:**
- (a) − (b2), large companies: P@4 **+0.03 [−0.06, +0.13]**, not significantly different (n = 16). R@all +0.08 [+0.03, +0.14].
- (a) − (c), n = 31: P@4 +0.63 [+0.52, +0.73].
- (a) − baseline, n = 48: P@4 +0.43 [+0.33, +0.53].

### 3b. Sensitivities (`results/sensitivity.json`)

**Verbatim-only labels.** Each ground-truth entity keeps only the strings that appear verbatim in its excerpt, which drops the LLM-added aliases. The verbatim-only column in §3a shows the effect:
- P@4 for (a) falls from 0.53 to 0.48.
- For large companies it falls from 0.63 to 0.53.
- For (b2), large companies, it falls from 0.59 to 0.50.
- The small-company number is unchanged.

**Retrieval coverage confound.** This is the share of a company's ground-truth entities that appear anywhere in the search text the pipeline saw:

| Coverage definition | Large | Mid | Small |
|---|---|---|---|
| Verbatim, case-sensitive | 0.38 [0.29, 0.49] | 0.42 [0.29, 0.57] | **0.19** [0.08, 0.32] |
| Any alias, case-insensitive | 0.43 | 0.49 | 0.20 |

- **The free search returned much less about small companies' real competitors.** The small-vs-large precision gap therefore mixes model knowledge with retrieval coverage, and this design cannot separate the two.
- Splitting companies at the median coverage gives (a) P@4 of 0.47 at or below the median (n = 26, of which 13 are small) and 0.60 above it (n = 22, of which 3 are small).

**Thin-scrape claim support.**
- The "0.20" figure rests on **3 companies, 30 claims**: ROKU 0/14, ARLO 0/7 and SNAP 6/9. Claims within one company are not independent.
- The claim-level Wilson 95% CI is [0.10, 0.37], against 0.67 [0.62, 0.71] for scrapes of 1,000 characters or more (n = 469). This is descriptive only.

### 3c. Few-shot leak (Adyen / Braintree / Square)
- **Not reproduced.** None of the 148 seed-0 discovery outputs from the original prompt (a, b, b2, c) contain these names, and none of the 188 raw responses do.
- The scorer's own leak detector was broken until commit `8b3f5f0`; see the Change log. After the fix it also reports 0.
- The Stripe demo (claude-haiku-4-5) returns Adyen, PayPal, Square and Braintree. Those are genuine Stripe competitors, so the demo is not evidence of copying.
- The leak remains **untested for Haiku**.

### 3d. Pipeline aborts
- 8 of 48 homepages (17%) gave no text to the plain-HTTP scraper: Uber, Supermicro, Wayfair, Ubiquiti, Weatherford, NETGEAR, Aviat and Phunware.
- `report.py` would stop on these. Discovery was still scored for them, using the product's fallback industry ("technology").

### 3e. Claim support of step-2 profiles (NLI judge, `cross-encoder/nli-deberta-v3-large`, threshold 0.5)
- **The judge is only moderately reliable.** I validated it on 300 sentences from a local RAGTruth test copy that carries human labels:
  - balanced accuracy 0.657 [0.603, 0.709]
  - κ 0.31 [0.21, 0.42]
  - AUROC 0.71
- **Overall support.** Across 40 profiles and 499 claims, 0.64 [0.56, 0.71] of claims are supported, averaged over companies.
- **By tier.** Large 0.63, mid 0.59, small 0.70. The CIs overlap.
- **Human-labelling file.** `results/claims_sample.csv` holds 100 claims with an empty `human_label` column. No result depends on it.

## 4. What the numbers support, and what they don't

**Supported** (one model, one run, free search):
- P@4 is 0.53 [0.43, 0.62], or 0.48 with verbatim-only labels. The non-LLM baseline scores 0.10.
- Small companies score much lower (P@4 0.26) than large (0.63) or mid (0.70). **The search text contains far fewer of small companies' real competitors (coverage 0.19 vs 0.38), so this gap cannot be attributed to the model alone.**
- The extraction step depends on its evidence. Given another company's search text, it returns nothing 84% of the time, and its P@4 drops to 0.03. This holds on 31 large- and mid-cap companies.
- For large companies, the model's own knowledge ((b2), added post hoc) is **not significantly different** from the full pipeline in P@4: +0.03 [−0.06, +0.13], n = 16. Retrieval does add recall.

**Not supported:**
- "Grounding matters more for the long tail." The small and mid (b2) runs did not happen.
- Anything about the shipped Haiku + Tavily configuration, report quality, or seed variance.
- That a few-shot leak exists.

## 5. Threats to validity
- **ddgs is not Tavily.** Results and coverage differ, and they drift over time.
- **10-K lists are incomplete.** A correct prediction missing from the 10-K counts as wrong, so P@4 is a lower bound.
- **Labels are LLM-assisted.** They are checked for literal presence in the filing excerpt, but not reviewed by a human. Five label sets were incomplete before review and are now fixed (see the Change log).
- **Fame proxy.** Public float is not the same as how familiar an LLM is with a company.
- **Selection bias.** The 48 companies were chosen for naming competitors in their filings.
- **(b2) is post hoc.** It was added after (b) produced empty output for every company.
- **(c)'s n = 31 is a quota-truncated subset, not a random sample.** Runs went large first, then mid, and the quota ended before any small company ran.
- **(b2)'s 21 companies are also truncated.** They are all 16 large companies plus the first 5 mid ones.
- **Possible label leakage into search.** Web pages can paraphrase a 10-K. Only sec.gov itself was excluded.
- **The NLI judge is moderately reliable** (κ 0.31).
- **Third-party text.** `raw/retrieval/*.json` contains excerpts of third-party web pages. `strip_retrieval.py` is prepared but not run; the user decides.
- **One run.** There is no seed variance.

## 6. Change log

**Product code (`backend/`): no changes.** It is byte-identical to `c3eac2d` and its suite still passes 25/25. There are 25 tests at `c3eac2d`. `raw/test_after_fix.txt` shows "26 passed" only because it was produced with the unapplied few-shot patch (+1 test) in place. The `eval_sop/tests` suite has 33 tests (`test_build_gt` 3, `test_transport` 26, `test_score` 4).

| Commit | Change | Why / evidence | Preserved |
|---|---|---|---|
| `0f658d7`, `3d9532c` | Harness, ground truth, seed-0 results | — | — |
| (in `3d9532c`) | Few-shot fix researched, **not applied**; kept as `proposed_fewshot_fix.patch` | Leak not reproduced (§3c). The patch's comments wrongly said the leak was "measured"; now corrected to "not observed; precaution" (fix-phase commit). `git apply --check` still passes. | Product prompt |
| `0cb395c` | Groq org ID redacted from `raw/discovery.log`. Added an opt-in `strip_retrieval.py`. | Privacy review. **The org ID is still present in commit `3d9532c`.** History was not rewritten; squash before any push. | Retrieval files untouched |
| `bf6b8e1` | `build_gt.py` decodes HTML from `r.content` (charset from the header, or sniffed) instead of `r.text`. Dropped a reference to a non-existent PROVENANCE.md. | Reproduced: `raw/encoding_repro.txt` shows the old path turning "Nestlé" into "NestlÃ©". A scan of all 48 cached 10-K texts found no mojibake, so labels were unaffected. | Cache, labels |
| `a8107fe` | Ground truth completed from the stored excerpts with a new `--offline` rebuild (no EDGAR calls). Added NTGR Synology, TP-Link, TRENDnet, Ubiquiti and WatchGuard (span now ends at the enterprise bullet); CNDT Leidos, TransCore, Thales, Cubic and INIT; WDAY NetSuite; BOX OpenText. Added the aliases Belden, Vistance and Resideo. | Review found truncated spans; I re-audited every excerpt for unlabelled capitalised names. P@4 for (a) went 0.524 → 0.529. | No labels removed |
| `65cc8e0` | New `LLMShim` transport covering the items below. Tests use a fake client: usage, 429, 400/401/403/404, the cap, crash/resume, model pinning, and exact replay of the Groq run. | Paid-run readiness | Groq cache keys unchanged (replay test) |
| `65cc8e0` (cont.) | Haiku provider pinned to `claude-haiku-4-5-20251001`. Uses the official SDK with `max_retries=0`, sends no `seed` or `reasoning_effort`, and records `model_reported`. | Paid-run readiness | |
| `65cc8e0` (cont.) | Persisted cost ledger at $1/M input and $5/M output. A call is refused if the worst case would pass the cap (default $2.75). | Paid-run readiness | |
| `65cc8e0` (cont.) | At most 3 attempts per call (was up to 400). As committed, any non-429 status that was not an `InternalServerError` failed fast, which wrongly included 529/503. Corrected in `fc943ac`: 429 and all 5xx retry; other 4xx fail fast. | Paid-run readiness | |
| `65cc8e0` (cont.) | The shim now rejects any `model` argument other than its pinned model. | Paid-run readiness | |
| `8b3f5f0` | Leak detector fixed. `score.py` contained literal backspace characters where `\b` was intended, so it could never match. | Reproduced: `tests/test_score.py` failed (`raw/leak_detector_before_fix.txt`) and passes after the fix. Leak rates stay 0, which agrees with the independent raw-response check. | |
| `5116815` | No model mixing. Model added to the resume key. Haiku output goes to `discovery_haiku.jsonl`. Scoring groups by model and pairs only within a model. | Review item A3 | Groq numbers unchanged |
| `5116815` (cont.) | Haiku design set to {a, b2, c, d} once at T=0, and `--dry-run` added. | Review item A4 | |
| `53dcc63` | `sensitivity.py` added | §3b | |
| `15099b5` | Round 2: spend safety | See below | |
| `15099b5` (cont.) | An exclusive lock file is taken next to the ledger; a second process gets `LedgerLocked`. | Reviewer script `raw/adv_before_round2.txt`: two processes on one ledger billed $0.099 against a $0.05 cap. | |
| `15099b5` (cont.) | Reserve-then-settle ledger rows: the worst case is reserved before every attempt and the cap re-checked each time. Timeouts, connection errors, 5xx and interrupts stay charged at the worst case; 429/4xx settle at $0. Rows are fsynced. | Billed timeouts went unrecorded: ledger $0.0045 vs billed $0.0135. Failing tests in `raw/spend_safety_before_fix.txt`. | |
| `15099b5` (cont.) | The estimate counts UTF-8 bytes, and `base_url` is pinned to api.anthropic.com. | Review item | |
| `fc943ac` | 529 `OverloadedError` and 503 retried and charged at the worst case | Both subclass `APIStatusError` directly in SDK 0.93 (`raw/529_before_fix.txt`) | |
| `cc9d581` | `build_gt.py` refuses to write on any problem | Failing test: `raw/build_gt_refuse_before_fix.txt`. The real rebuild is unchanged. | Labels |
| `86e4370` | The tautological estimate test is replaced by a check against the 188 real Groq prompt_token counts. The estimate divisor goes from 3 to 2 (`max(chars, bytes)/2 + 50`). | At /3, 1 of 188 prompts was under-estimated (ratio 0.84, `raw/estimate_before_fix.txt`); /2 gives a minimum ratio of 1.25. The Groq tokenizer stands in for Claude's. | |
| `86e4370` (cont.) | The replay test now fails if it tries to make any API call, even with keys set. | Review item | |
| (round 3, this commit) | Ledger, lock and Haiku cache moved from `eval_sop/raw/` to `%LOCALAPPDATA%\sop_eval\competitor_insight\`, with no env override. Lock errors now report whether the PID in the lock file is running (psutil) and leave recovery manual. | Shared spend record across worktree and main checkout. Failing tests first: `raw/state_dir_before_fix.txt`. | Groq cache stays in the repo |
| `e42b3c1` | The scorer flags responses that hit max_tokens (`truncated`, `n_truncated`) instead of silently counting them as empty | Groq run: 0 truncated in every group; metrics unchanged. Failing tests: `raw/truncation_before_fix.txt`. | |

## 7. Proposed, not done
- **README test count.** Lines 207, 272 and 327 say "22 offline unit tests". There are 25, and 2 of them need DNS (`test_ssrf_allows_public` and `test_reachability_checks_do_not_follow_redirect_chains`; see `check_tests_offline.py` and `raw/tests_offline.txt`). Suggested wording: "25 unit tests (23 fully offline; 2 resolve DNS)".
- **Few-shot patch.** Apply it only if the leak is shown with the production model.
- **Scrape aborts.** Fall back to search snippets instead of aborting when the homepage can't be scraped (17% of companies).
- **Wording.** Describe the system as a fixed LLM pipeline, not an agent. The LLM never calls tools. The README does not say "agent".
- **History.** Squash the branch before pushing, because of the org ID in `3d9532c`.

## 8. Paid run, prepared but not executed
- **What it is: "Haiku on the fixed ddgs evidence."** It runs `claude-haiku-4-5-20251001` on exactly the cached `raw/retrieval/` search text, over 48 companies × {a_full, b2, c_shuffled, d_fixed}, once at T=0. That is 192 calls.
- **What it is not.** It is **not** the shipped Haiku + Tavily configuration and must never be described as such.
- **Dry run.** `EVAL_PROVIDER=anthropic python eval_sop/run_discovery.py --dry-run` gives a **worst-case total of $1.1884** (`results/haiku_dry_run.txt`). It was $1.0175 before the estimate change in `86e4370`. The worst case assumes max(chars, UTF-8 bytes)/2 + 50 input tokens and the full 700 output tokens.
- **Where the spend record lives.** The cost ledger, its lock and the Haiku response cache are in one fixed user-level directory outside the repo, `%LOCALAPPDATA%\sop_eval\competitor_insight\` (`common.STATE_DIR`). A run from this worktree and a run from the main checkout therefore share a single spend record. There is no env override. Haiku discovery outputs still go to `eval_sop/raw/discovery_haiku.jsonl`; copy the cache into the repo after the run if it should be committed.
- **Run safety.** Only one process may use the ledger, enforced by the lock file. If the lock exists, the error says whether the PID inside it is still running or the lock is stale; recovery is always manual: confirm nothing is running, then delete the lock. Each attempt is reserved at the worst case before it is sent. The cap can only be passed if a single response's real input exceeds the estimate; the estimate checked out above all 188 real counts, with a minimum ratio of 1.25.
- **Scoring the Haiku run.** Score it with `EVAL_PROVIDER=anthropic` so the truncation check can see the Haiku cache. Otherwise those rows report `n_truncation_unknown`.
- **Cap.** $2.75, inside this project's $3 share.
- **What it allows.** A clean Haiku comparison of (a) vs (b2) by tier, including small companies, the leak test for Haiku, and (d).
- **Command.** `EVAL_PROVIDER=anthropic EVAL_KEY_ENV=<.env> EVAL_KEY_VAR=ANTHROPIC_API_KEY python eval_sop/run_discovery.py`
- **Model ID check.** The pinned ID `claude-haiku-4-5-20251001` was required by the review. The current Anthropic model list names `claude-haiku-4-5`. If the dated ID returns 404, the shim fails fast at $0. Switching IDs is then a one-line change in `common.py`.
- **Free remainder (Groq, same model).** The leftover Groq conditions need about 0.7M tokens, roughly 4 days of free quota.

## 9. SOP-ready sentences (true for this run)
1. "I built a 48-company ground-truth set from the Competition sections of SEC 10-K filings. The labels are LLM-assisted, and each labelled competitor appears verbatim in the filing's Competition passage. On it, my competitor-discovery pipeline (the qwen3.8-27b model served on Groq, free web search, single run) reached precision@4 of 0.53 (95% CI 0.43–0.62; 0.48 counting only names exactly as written in the filing), against 0.10 for a non-LLM baseline."
2. "For large-cap companies, the model's parametric knowledge alone (a condition I added after the first run) was not significantly different in precision from the retrieval pipeline (0.59 vs 0.63, n=16). Precision fell to 0.26 for small caps, but the search results also contained far fewer of their true competitors, so that gap mixes model knowledge with retrieval coverage."
3. "An evidence-shuffling ablation on 31 large- and mid-cap companies showed that the extraction step depends on its evidence: given another company's search results, it returned no competitors 84% of the time."
