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
| Replay (no API calls) | `python eval_sop/score.py && python eval_sop/sensitivity.py` (install `backend/requirements.txt` + `eval_sop/requirements.txt`; nothing else is needed and no key is read). `tests/test_transport.py` checks that all 148 discovery records replay exactly from the cache. |
| Fresh run | `EDGAR_UA="Competitor-Insight-Engine noreply@users.noreply.github.com" python eval_sop/ground_truth/build_gt.py` (SEC asks for a contact in the User-Agent; use a no-reply address, not a personal one), then `retrieve.py`, `run_discovery.py` and `score.py`. Set the key with `EVAL_KEY_ENV` / `EVAL_KEY_VAR`. |

### 2. Ground truth (`eval_sop/ground_truth/`)
- **Source.** Each company's latest 10-K on EDGAR; accession, URL and filing date are in `companies.json`.
- **How the labels were made.** The labels are **LLM-assisted**: Claude transcribed the competitor names from each excerpt and added aliases. `build_gt.py` refuses to write `companies.json` (SystemExit) unless every labelled entity has its name, or one of its aliases, appearing verbatim in the stored 10-K excerpt. That refusal was added in `da5ad63`; before it, problems were only printed. All 48 companies pass. Labels have not been reviewed by a human.
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
- The scorer's own leak detector was broken until commit `cf15d45`; see the Change log. After the fix it also reports 0.
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
- **Third-party text.** `raw/retrieval/*.json` contains excerpts of third-party web pages. `strip_retrieval.py` is prepared and deliberately **not run**. This is an open decision, not a settled one — see §7.
- **One run.** There is no seed variance.

## 6. Change log

**Product code (`backend/`): no changes.** It is byte-identical to `c3eac2d` and its suite still passes 25/25. There are 25 tests at `c3eac2d`. `raw/test_after_fix.txt` shows "26 passed" only because it was produced with the unapplied few-shot patch (+1 test) in place.

**Test counts as they stand.** `backend/tests` 25 passed. `eval_sop/tests` collects **81** tests (`test_build_gt` 3, `test_transport` 74, `test_score` 4) and in **a clean clone runs 80 passed + 1 skipped**, not 81 passed: see §7 on the gitignored EDGAR cache. In this working tree, where that cache exists, it is 81 passed. Both suites in one pytest process at the repo root: **106 passed** (that used to be 3 failures; see the `c5bdf46` row below). Ten of those tests are the round-5 state-directory cases.

| Commit | Change | Why / evidence | Preserved |
|---|---|---|---|
| `0f658d7`, `37fb65f` | Harness, ground truth, seed-0 results | — | — |
| (in `37fb65f`) | Few-shot fix researched, **not applied**; kept as `proposed_fewshot_fix.patch` | Leak not reproduced (§3c). The patch's comments wrongly said the leak was "measured"; now corrected to "not observed; precaution" (fix-phase commit). `git apply --check` still passes. | Product prompt |
| `37fb65f` | Groq org ID redacted from `raw/discovery.log`. Added an opt-in `strip_retrieval.py`. | Privacy review. The redaction and the results commit are now one commit, so no commit on this branch contains the unredacted log (see §6a). | Retrieval files untouched |
| `aa90862` | `build_gt.py` decodes HTML from `r.content` (charset from the header, or sniffed) instead of `r.text`. Dropped a reference to a non-existent PROVENANCE.md. | Reproduced: `raw/encoding_repro.txt` shows the old path turning "Nestlé" into "NestlÃ©". A scan of all 48 cached 10-K texts found no mojibake, so labels were unaffected. | Cache, labels |
| `9f92ca7` | Ground truth completed from the stored excerpts with a new `--offline` rebuild (no EDGAR calls). Added NTGR Synology, TP-Link, TRENDnet, Ubiquiti and WatchGuard (span now ends at the enterprise bullet); CNDT Leidos, TransCore, Thales, Cubic and INIT; WDAY NetSuite; BOX OpenText. Added the aliases Belden, Vistance and Resideo. | Review found truncated spans; I re-audited every excerpt for unlabelled capitalised names. P@4 for (a) went 0.524 → 0.529. | No labels removed |
| `9a683a5` | New `LLMShim` transport covering the items below. Tests use a fake client: usage, 429, 400/401/403/404, the cap, crash/resume, model pinning, and exact replay of the Groq run. | Paid-run readiness | Groq cache keys unchanged (replay test) |
| `9a683a5` (cont.) | Haiku provider pinned to `claude-haiku-4-5-20251001`. Uses the official SDK with `max_retries=0`, sends no `seed` or `reasoning_effort`, and records `model_reported`. | Paid-run readiness | |
| `9a683a5` (cont.) | Persisted cost ledger at $1/M input and $5/M output. A call is refused if the worst case would pass the cap (then a $2.75 default that `EVAL_COST_CAP` could override; made a project hard maximum in `c5bdf46`). | Paid-run readiness | |
| `9a683a5` (cont.) | At most 3 attempts per call (was up to 400). As committed, any non-429 status that was not an `InternalServerError` failed fast, which wrongly included 529/503. Corrected in `369f294`: 429 and all 5xx retry; other 4xx fail fast. | Paid-run readiness | |
| `9a683a5` (cont.) | The shim now rejects any `model` argument other than its pinned model. | Paid-run readiness | |
| `cf15d45` | Leak detector fixed. `score.py` contained literal backspace characters where `\b` was intended, so it could never match. | Reproduced: `tests/test_score.py` failed (`raw/leak_detector_before_fix.txt`) and passes after the fix. Leak rates stay 0, which agrees with the independent raw-response check. | |
| `fe10699` | No model mixing. Model added to the resume key. Haiku output goes to `discovery_haiku.jsonl`. Scoring groups by model and pairs only within a model. | Review item A3 | Groq numbers unchanged |
| `fe10699` (cont.) | Haiku design set to {a, b2, c, d} once at T=0, and `--dry-run` added. | Review item A4 | |
| `49f7870` | `sensitivity.py` added | §3b | |
| `cfffc09` | Round 2: spend safety | See below | |
| `cfffc09` (cont.) | An exclusive lock file is taken next to the ledger; a second process gets `LedgerLocked`. | Reviewer script `raw/adv_before_round2.txt`: two processes on one ledger billed $0.099 against a $0.05 cap. | |
| `cfffc09` (cont.) | Reserve-then-settle ledger rows: the worst case is reserved before every attempt and the cap re-checked each time. Timeouts, connection errors, 5xx and interrupts stay charged at the worst case; 429/4xx settle at $0. Rows are fsynced. | Billed timeouts went unrecorded: ledger $0.0045 vs billed $0.0135. Failing tests in `raw/spend_safety_before_fix.txt`. | |
| `cfffc09` (cont.) | The estimate counts UTF-8 bytes, and `base_url` is pinned to api.anthropic.com. | Review item | |
| `369f294` | 529 `OverloadedError` and 503 retried and charged at the worst case | Both subclass `APIStatusError` directly in SDK 0.93 (`raw/529_before_fix.txt`) | |
| `da5ad63` | `build_gt.py` refuses to write on any problem | Failing test: `raw/build_gt_refuse_before_fix.txt`. The real rebuild is unchanged. | Labels |
| `3c9a167` | The tautological estimate test is replaced by a check against the 188 real Groq prompt_token counts. The estimate divisor goes from 3 to 2 (`max(chars, bytes)/2 + 50`). | At /3, 1 of 188 prompts was under-estimated (ratio 0.84, `raw/estimate_before_fix.txt`); /2 gives a minimum ratio of 1.25. The Groq tokenizer stands in for Claude's. | |
| `3c9a167` (cont.) | The replay test now fails if it tries to make any API call, even with keys set. | Review item | |
| `5c5b382` | Ledger, lock and Haiku cache moved from `eval_sop/raw/` to `%LOCALAPPDATA%\sop_eval\competitor_insight\`, with no env override. **The "no env override" half of this was false when written** — `%LOCALAPPDATA%` *is* an env override; corrected in the `round 5` row below. Lock errors now report whether the PID in the lock file is running (psutil) and leave recovery manual. | Shared spend record across worktree and main checkout. Failing tests first: `raw/state_dir_before_fix.txt`. | Groq cache stays in the repo |
| `240fbb1` | The scorer flags responses that hit max_tokens (`truncated`, `n_truncated`) instead of silently counting them as empty | Groq run: 0 truncated in every group; metrics unchanged. Failing tests: `raw/truncation_before_fix.txt`. | |
| `c798dce` | `build_gt.py`'s documented `EDGAR_UA` example, and the §1 "Fresh run" line, use a GitHub no-reply address instead of a personal one. SEC asks for a contact in the User-Agent; it does not ask for a personal mailbox. | Privacy review of the only place this repo tells a reader to put an email address. No code path changed: `EDGAR_UA` was already read from the environment. | Labels, cache, results |
| `abfacc7` | Documentation only. Every stale commit hash this file cited was remapped to the rewritten commit with the same subject (13 hashes; `0f658d7` and `c3eac2d` were already valid). The superseded privacy claim was replaced by §6a, which states only what was verified commit by commit. | The rewrite described in §6a changed the hashes. Staleness was tested with `git merge-base --is-ancestor`, not `git cat-file -e`. | No code, data or results touched |

| `c5bdf46` | **The cap is now a project hard maximum, not a default.** `common.PROJECT_HARD_MAX_USD = 2.75`, and `check_cap()` rejects any cap that is not a finite positive number at or below it. `EVAL_COST_CAP` may only *lower* the cap. `LLMShim.__init__` validates its `cap` argument through the same function. | `EVAL_COST_CAP` silently overrode the documented $2.75 cap, so the figure in §8 was not enforceable. Worse, `EVAL_COST_CAP=nan` disabled spending control entirely: `nan` fails every comparison, so `spent + worst > cap` was always False. Failing tests first: 38 new parametrised cases in `tests/test_transport.py` cover `nan`, `NaN`, `inf`, `-inf`, `0`, `-1`, `-0.01`, `2.76` and `1e9` through `check_cap()`, through `cap_from_env()`, through the shim constructor, and through the command line (a subprocess running `run_discovery.py --dry-run`, which refuses at import). Follows the sibling project's `eval_sop/budget.py` (`check_cap` / `PROJECT_HARD_MAX_USD`). | Ledger format, cache keys, all results |
| `c5bdf46` (cont.) | **Cross-suite state pollution fixed.** `eval_sop/common.py` no longer assigns `analyzer.llm_call = shim` at import; the assignment moved into `common.install_shim()`, called by `retrieve.py` and `run_discovery.py` at their entry points. The replay test installs it with `monkeypatch` and also sets `analyzer.COMPETITOR_EXTRACTION_PROMPT` through `monkeypatch` rather than by assignment. | `python -m pytest -q` at the repo root was **red**: 3 backend tests failed (`test_llm_call_retries_without_temperature_when_rejected`, `..._keeps_temperature_when_accepted`, `..._does_not_swallow_unrelated_bad_requests`) and passed in isolation. Mechanism: both suites share `sys.modules["analyzer"]`, so importing the harness replaced the product's transport under the product's own tests. Regression test: `test_importing_the_harness_does_not_patch_the_product_transport`. | Harness behaviour (the entry points install the shim as before) |
| `c5bdf46` (cont.) | `eval_sop/requirements.txt` (pytest, ruff, psutil, anthropic, httpx) and `eval_sop/requirements-optional.txt` (ddgs; torch, transformers, pandas, scikit-learn) added, and README gained an install + run section for the harness. | Nothing declared the harness's dependencies; a reviewer had to add them by hand. Verified by building a fresh venv from the new README lines alone: 25 backend, 71 `eval_sop`, 96 at the root (81 and 106 after the round-5 tests landed), and `score.py` + `sensitivity.py` reproduced `results/*.json` byte-for-byte. | — |
| `c5bdf46` (cont.) | README's "22 offline unit tests" corrected to "25 unit tests (23 fully offline; 2 resolve DNS)" in all three places. | The branch shipped a README that §7 itself documented as false. | — |
| `b8b4a16`, `47da243` and this row's own commit | Documentation only. §6a rewritten to the re-verified position (16 subject-matched pairs, trees identical; tip tree no longer identical to the pre-rewrite tip). The two `(round N, this commit)` labels replaced by `5c5b382` and `abfacc7`. A row added for `c798dce`. The machine username and the quoted drive-rooted path removed from §6a, so this file is no longer a hit for the scan it describes. §7 rewritten as the owner's two open decisions plus what the uncommitted EDGAR cache costs; the README test-count item moved to done. The post-redaction scan was then re-run and found the username still in this file in two earlier commits — removed afterwards by the tree filter in §6b. | Each claim re-verified in this repository before it was written. | No code, data or results touched |
| round 5, this row's own commit | **`STATE_DIR` no longer derives from `%LOCALAPPDATA%`.** `common.py:57` now resolves `Path.home() / ".sop_eval" / "competitor_insight"`, matching the sibling projects. No environment variable can move the ledger, its lock or the Haiku cache. | **A spend bug, found by an independent check, not by this suite.** Setting `LOCALAPPDATA` relocated all three: measured `C:\…\AppData\Local\sop_eval\competitor_insight` → `<tmp>\sop_eval\competitor_insight`. A fresh ledger means $0.00 spent, so the $2.75 cap re-arms and any earlier spend is forgotten; the lock moves with it, so two paid runs can overlap. Worse, **the round-3 test asserted the variable's value, so the suite certified the defect**, and the comment above the line claimed "Deliberately no env override" while the line read an env var. Failing tests first: 10 new cases — one per variable for `LOCALAPPDATA`, `APPDATA`, `XDG_STATE_HOME`, `TEMP`, `TMP`, `HOME`, `HOMEDRIVE`, `HOMEPATH`, one with all of them redirected at once, and one asserting the lock sits beside the ledger. Each resolves `STATE_DIR` in a **child process**: reloading the module in-process pollutes module identity for other tests. 3 were red (`LOCALAPPDATA` individually, all-at-once, and the round-3 assertion), the other 7 vars never moved it. | The old directory was **empty — no ledger, $0 spent** — so there was nothing to migrate. §8 corrected; its "no env override" claim is now true and tested |
| `054520d` and this row's own commit | Documentation only. **A second history rewrite**, recorded in the new §6b: a `--tree-filter` over `c3eac2d..HEAD` replacing the username with `<user>` in `RESULTS.md`, which removed the last trace of it from history without collapsing the change log. §6a now says the branch was rewritten twice and re-derives its pairing figures; §9's history item is closed; the four hashes the filter moved were remapped by subject. | Redacting the working tree had left the line in the two commits that carried it — the first attempt mistook a tip-level edit for a history fix. Squashing `c3eac2d..HEAD`, which §6a previously proposed, would have destroyed the whole range to fix one line. Verified at the moment the filter finished: commit count preserved, `git diff backup/pre-resultsscrub-competitor HEAD` empty, 0 username matches on `sop-eval` against 2 on the backup as the positive control. | No code, data or results touched; the tip tree was byte-identical to the pre-filter tip |

### 6a. History rewrite, and what is actually in it now

`sop-eval` has been rewritten **twice**. This section describes the first
rewrite; §6b describes the second. Both are local only — nothing has been
pushed at any point, so neither rewrite changed history that anyone else held.

The first rewrite was a **squash and replay, not a `--tree-filter`**: the two commits that
recorded the seed-0 results and then redacted the Groq organisation ID were
squashed into the single commit `37fb65f`, and every later commit was replayed
onto it, so every hash after `0f658d7` changed. The hashes cited in this
document were remapped by matching commit subjects.

Re-verified here by pairing the 24 commits in `c3eac2d..HEAD` against the 18 in
`c3eac2d..backup/pre-squash-competitor` by subject: **16 pairs match by subject,
and for all 16 `git diff <old> <new>` is empty** — the replay changed no tree it
carried over. The unmatched commits are all expected: two on the backup side are
the pair that was squashed away, and seven on `sop-eval` are `37fb65f` itself,
the squash product, plus the seven commits that landed *after* the first rewrite.
(Eight sop-eval-only subjects, 16 matched: 16 + 8 = 24. Re-derive these before
quoting them -- every commit added since moves them.)

Because of those later commits, **the branch tip's tree is no longer identical to
the pre-rewrite tip**, and `git diff backup/pre-squash-competitor HEAD` is
non-empty by exactly that work. An earlier version of this section claimed
tip-tree identity and "all fifteen pairs". Both were true when written; both are
corrected above. The figures in this paragraph are re-derived, not carried
forward — the second rewrite (§6b) changed the commit count again.

`backup/pre-squash-competitor` is the branch that keeps the pre-rewrite objects,
including `3d9532c` with the unredacted Groq organisation ID. It is local only
and **must never be pushed**. It is also why pre-rewrite SHAs still resolve in
this repository — see the note at the end of this section.

Verified in this repository, commit by commit over `c3eac2d..HEAD`:

- **The Groq organisation ID survives in no commit.** `git grep` for the
  literal ID over every commit on `sop-eval` returns nothing. The same scan
  over `backup/pre-squash-competitor` returns exactly one commit (`3d9532c`),
  which is the positive control that the scan works.
- **No machine path reaches any code, data or result, in any commit — and as of
  the second rewrite, none reaches any file.** `git grep -I -i` over every commit
  on `sop-eval`, for the machine username and for a drive-rooted user path in
  both slash directions, now returns **nothing**. It previously hit two commits
  and one file: `RESULTS.md` itself, one line each, where the prose of this very
  bullet quoted the terms it greps for — the audit text was its own only hit.
  Redacting the working tree was not enough, because the two earlier commits kept
  the line. The second rewrite in §6b fixed exactly that one line in exactly
  those two commits. The positive control is
  `backup/pre-resultsscrub-competitor`, where the same scan still returns those
  two commits, so the scan demonstrably works.
  No commit, before or after the redaction, puts a machine path in
  `backend/`, `eval_sop/*.py`, the ground truth, the caches or `results/`.
  The only matches for `AppData` and `OneDrive` are benign and deliberate: at the
  tip, `AppData` survives only in this file, discussing the variable the state
  directory no longer uses, and Microsoft **OneDrive** appears as a labelled
  competitor in the 10-K ground truth and the retrieval cache. Earlier commits
  also match in `eval_sop/common.py` and `eval_sop/tests/test_transport.py`, from
  when the state directory was derived from `%LOCALAPPDATA%`.
- **Commit messages are clean.** The only match across `c3eac2d..HEAD` is the
  literal `%LOCALAPPDATA%` in one subject line.
- **A backup of the pre-rewrite history exists locally** on the branch
  `backup/pre-squash-competitor`. It is local only; it must not be pushed,
  because `3d9532c` on it still carries the unredacted log.

The superseded claim, kept for the record: the change log previously said the
org ID was "still present in commit `3d9532c`", that history "was not
rewritten", and that the branch had to be squashed before any push. That was
true when written. It no longer describes this branch.

### 6b. Second history rewrite: the username in this file

The redaction recorded in the change log cleaned the **working tree**, but the
two commits that introduced and carried the offending line kept it. Redacting a
file at the tip does not remove it from history — a point worth stating plainly,
because the first attempt here made exactly that mistake.

The fix was a **`--tree-filter` over `c3eac2d..HEAD`** replacing the username
with `<user>` in `RESULTS.md` and nothing else. It was chosen over squashing
`c3eac2d..HEAD`, which the previous version of §6a proposed, because squashing
would have collapsed the whole range — including the reproduce-before-fix pairs that
are the point of the change log — into one, to fix a single line. The filter
preserves every commit.

Verified after the rewrite:

- **The filter preserved every commit and changed no delivered content.** Both
  properties were measured at the moment the filter finished, against
  `backup/pre-resultsscrub-competitor`, which is the pre-filter tip: equal commit
  counts, and `git diff backup/pre-resultsscrub-competitor HEAD` empty. The filter
  touched only intermediate blobs.
  **Commits have landed since**, so neither comparison is empty or equal any more,
  and that is expected rather than a regression: `git diff` against that backup
  now shows exactly the work committed after the filter, and `c3eac2d..HEAD` is
  longer by the same number of commits. The check that does not go stale is the
  one in §6a — 16 subject-matched pairs with empty diffs — plus the scan below.
  Re-derive the counts before quoting them; the earlier version of this bullet
  asserted "23 commits" and "diff empty" and was falsified by the very next
  commit, which is the failure mode this document keeps having to correct.
- **The scan is clean and the control fires**: the username matches 0 commits on
  `sop-eval` and still matches 2 on `backup/pre-resultsscrub-competitor`.
- **Commit messages were never affected** — 0 matches on either branch.
- Only four hashes moved, because `filter-branch` reuses a commit whose tree and
  parent are both unchanged: everything before the first edited commit kept its
  hash. The four were remapped by subject, each matching exactly one commit, and
  every hash this document cites was then re-checked with
  `git merge-base --is-ancestor`. `3d9532c` remains a deliberate exception: it
  exists only on `backup/pre-squash-competitor`, which is the point of citing it.

`backup/pre-resultsscrub-competitor` holds the pre-filter objects and **must
never be pushed**, for the same reason as the other backup branch.

A note on how to check this, because the obvious check is wrong: `git cat-file
-e <sha>` **succeeds for pre-rewrite SHAs** here, because
`backup/pre-squash-competitor` keeps the old objects reachable. Existence is
therefore not a staleness test. The valid test is reachability from the branch
tip: `git merge-base --is-ancestor <sha> HEAD`.

## 7. Open decisions for the owner

Two things on this branch are **not settled** and are not mine to settle. Neither
has been acted on; both are left exactly as they were.

1. **Whether to publish `eval_sop/raw/retrieval/*.json`.** These 48 files hold
   excerpts of third-party commercial web pages, scraped by `retrieve.py` and
   unlicensed for redistribution. They are currently **committed**, so pushing
   this branch publishes them. `eval_sop/strip_retrieval.py` would reduce them to
   hashes and is **deliberately unrun**. The consequence either way: keep them
   and the committed Groq run stays exactly replayable by anyone (`test_transport`
   replays all 148 records from them) but third-party copy is redistributed;
   strip them and the third-party text goes away but the public replay, the
   retrieval-coverage numbers in §3b and the `(c)` shuffled-evidence condition can
   no longer be reproduced from the repository alone.
2. **Whether to commit `eval_sop/raw/edgar_cache` (~20 MB).** It is gitignored
   today. The consequence of leaving it out is listed immediately below; the
   consequence of committing it is 20 MB of SEC filing text in the repository
   forever, and SEC filings are US government works, so the licensing question
   is the easy half.

**What depends on the uncommitted EDGAR cache.** Without it, in a clean clone:
- `eval_sop/tests/test_build_gt.py::test_build_refuses_to_write_when_a_label_is_not_in_the_excerpt`
  **skips** (`pytest.skip("10-K text cache not present (gitignored)")`). The suite
  is therefore **32 passed + 1 skipped** at the commit where §6 previously said
  "33 tests", and 80 passed + 1 skipped now. A reader must not take "the suite
  passes" as evidence that the refusal in `da5ad63` works — in a clean clone that
  test never runs.
- The §2 claims **"each labelled competitor appears verbatim in the stored 10-K
  excerpt"** and **"all 48 companies pass"** cannot be re-checked: the verbatim
  check reads the cached excerpts.
- The `--offline` ground-truth rebuild of `9f92ca7` cannot be re-run, so
  `companies.json` has to be taken on trust.
- The **no-mojibake scan over all 48 cached 10-K texts** cited for `aa90862`
  cannot be reproduced.
- The same holds for §9's first SOP sentence, which restates the verbatim claim.

## 7b. Proposed, not done
- **`eval_sop/` is not linted.** `backend/` has a pinned `ruff.toml` and CI runs
  ruff over it; `eval_sop/` pins the same `ruff==0.16.3` in its own
  `requirements.txt` but has no config of its own and no CI step, so nothing
  actually lints it. Under the product's rule set at a 130-column line
  length it reports 25 findings, mostly import ordering and now-redundant `noqa`
  markers, but including 3 `B023` closure-binds-loop-variable warnings at
  `score.py:248` that are worth a look before they are silenced. Not touched
  here: it is a cleanup pass, not a merge-gate fix.
- **Neither `backend/requirements.txt` nor CI's install line declares `pytest`
  and `httpx`** for the backend suite; CI passes them on the command line. The
  harness's new `requirements.txt` declares both, so installing it alongside the
  backend's makes `cd backend && pytest` work, but the backend half is still
  undeclared on its own.
- **Few-shot patch.** Apply it only if the leak is shown with the production model.
- **Scrape aborts.** Fall back to search snippets instead of aborting when the homepage can't be scraped (17% of companies).
- **Wording.** Describe the system as a fixed LLM pipeline, not an agent. The LLM never calls tools. The README does not say "agent".
- **History.** Nothing outstanding. The squash described in §6a removed the
  unredacted Groq log, and the tree filter in §6b removed the machine username
  from the two commits that still carried it, so neither appears in any commit on
  `sop-eval`. The standing housekeeping item remains: **do not push either backup
  branch** — `backup/pre-squash-competitor` still carries `3d9532c` with the Groq
  organisation ID, and `backup/pre-resultsscrub-competitor` still carries the
  username. Delete both before publishing.

## 8. Paid run, prepared but not executed
- **What it is: "Haiku on the fixed ddgs evidence."** It runs `claude-haiku-4-5-20251001` on exactly the cached `raw/retrieval/` search text, over 48 companies × {a_full, b2, c_shuffled, d_fixed}, once at T=0. That is 192 calls.
- **What it is not.** It is **not** the shipped Haiku + Tavily configuration and must never be described as such.
- **Dry run.** `EVAL_PROVIDER=anthropic python eval_sop/run_discovery.py --dry-run` gives a **worst-case total of $1.1884** (`results/haiku_dry_run.txt`). It was $1.0175 before the estimate change in `3c9a167`. The worst case assumes max(chars, UTF-8 bytes)/2 + 50 input tokens and the full 700 output tokens.
- **Where the spend record lives.** The cost ledger, its lock and the Haiku response cache are in one fixed user-level directory outside the repo, `~/.sop_eval/competitor_insight/` (`common.STATE_DIR`), resolved from `Path.home()`. A run from this worktree and a run from the main checkout therefore share a single spend record. **There is no environment-variable override** — and unlike the earlier version of this sentence, that is now true and tested. It previously read `%LOCALAPPDATA%`, which an independent check showed relocates the ledger, the lock and the cache together; see change-log row `round 5` and the nine tests in `test_transport.py` that redirect eight variables individually and all of them at once. Haiku discovery outputs still go to `eval_sop/raw/discovery_haiku.jsonl`; copy the cache into the repo after the run if it should be committed.
- **Run safety.** Only one process may use the ledger, enforced by the lock file. If the lock exists, the error says whether the PID inside it is still running or the lock is stale; recovery is always manual: confirm nothing is running, then delete the lock. Each attempt is reserved at the worst case before it is sent. The cap can only be passed if a single response's real input exceeds the estimate; the estimate checked out above all 188 real counts, with a minimum ratio of 1.25.
- **Scoring the Haiku run.** Score it with `EVAL_PROVIDER=anthropic` so the truncation check can see the Haiku cache. Otherwise those rows report `n_truncation_unknown`.
- **Cap.** $2.75, inside this project's $3 share, and **enforced as a project
  hard maximum**: `common.PROJECT_HARD_MAX_USD = 2.75`. `EVAL_COST_CAP` can only
  lower it. A cap that is not a finite positive number at or below $2.75 —
  including `nan`, `NaN`, `inf`, `-inf`, `0` and any negative — raises `ValueError`
  at import, so every entry point (including `--dry-run`) refuses before spending
  anything. Raising the ceiling is a deliberate source change, not an environment
  variable.
- **What it allows.** A clean Haiku comparison of (a) vs (b2) by tier, including small companies, the leak test for Haiku, and (d).
- **Command.** `EVAL_PROVIDER=anthropic EVAL_KEY_ENV=<.env> EVAL_KEY_VAR=ANTHROPIC_API_KEY python eval_sop/run_discovery.py`
- **Model ID check.** The pinned ID `claude-haiku-4-5-20251001` was required by the review. The current Anthropic model list names `claude-haiku-4-5`. If the dated ID returns 404, the shim fails fast at $0. Switching IDs is then a one-line change in `common.py`.
- **Free remainder (Groq, same model).** The leftover Groq conditions need about 0.7M tokens, roughly 4 days of free quota.

## 9. SOP-ready sentences (true for this run)
1. "I built a 48-company ground-truth set from the Competition sections of SEC 10-K filings. The labels are LLM-assisted, and each labelled competitor appears verbatim in the filing's Competition passage. On it, my competitor-discovery pipeline (the qwen3.8-27b model served on Groq, free web search, single run) reached precision@4 of 0.53 (95% CI 0.43–0.62; 0.48 counting only names exactly as written in the filing), against 0.10 for a non-LLM baseline."
2. "For large-cap companies, the model's parametric knowledge alone (a condition I added after the first run) was not significantly different in precision from the retrieval pipeline (0.59 vs 0.63, n=16). Precision fell to 0.26 for small caps, but the search results also contained far fewer of their true competitors, so that gap mixes model knowledge with retrieval coverage."
3. "An evidence-shuffling ablation on 31 large- and mid-cap companies showed that the extraction step depends on its evidence: given another company's search results, it returned no competitors 84% of the time."
