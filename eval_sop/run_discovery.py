"""Step 4 of the pipeline (competitor discovery) under several conditions.

Calls the product's analyzer.extract_competitors_from_search unchanged (prompt,
JSON parsing, blocklist, dedup), with only the system prompt and the search
content varied:

  a_full        original prompt (commit c3eac2d) + retrieved search content
  b_prior       original prompt + NO search content (LLM prior only)
  c_shuffled    original prompt + another company's search content (derangement, seed 0)
  d_fixed       candidate fixed prompt (fictional few-shot examples, eval_sop/fixed_prompt.py) + retrieved search content
  e_fixed_prior fixed prompt + NO search content
  b2_prior_knowledge  original prompt, search slot says "use your own knowledge" (LLM prior only)
  e2_fixed_prior_knowledge  fixed prompt, same "use your own knowledge" slot

b_/e_ were the first operationalisation of "prior only"; the model answered []
for all 48 companies (it abstains when told no search ran), so b2_/e2_ add an
explicit invitation to answer from parametric knowledge. Both are reported.

Groq run (committed, seed 0):
    python eval_sop/run_discovery.py --temps 0 --seeds 0

Haiku run ("Haiku on the fixed ddgs evidence": the same cached search text
as the Groq run, NOT the shipped Tavily configuration). Always dry-run first:
    EVAL_PROVIDER=anthropic python eval_sop/run_discovery.py --dry-run
    EVAL_PROVIDER=anthropic EVAL_KEY_ENV=<.env> EVAL_KEY_VAR=ANTHROPIC_API_KEY         python eval_sop/run_discovery.py
For Anthropic the defaults are conds {a_full, b2_prior_knowledge, c_shuffled,
d_fixed}, temperature 0, one pass (no seed is sent: the Messages API has none).
Outputs go to raw/discovery.jsonl (Groq) or raw/discovery_haiku.jsonl, and the
skip key includes the model, so models are never mixed.
"""

import argparse
import json
import random
import subprocess

from common import DEFAULT_CAP, MODEL, PROVIDER, ROOT, install_shim, load_companies, shim
from fixed_prompt import FIXED_COMPETITOR_EXTRACTION_PROMPT

import analyzer  # noqa: E402

RET = ROOT / "raw" / "retrieval"
OUT_DIR = ROOT / "raw"
BASE_COMMIT = "c3eac2d"


def original_prompt() -> str:
    src = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:backend/analyzer.py"],
        cwd=ROOT.parent, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    ns: dict = {}
    start = src.index("COMPETITOR_EXTRACTION_PROMPT = ")
    end = src.index('"""\n', src.index('"""', start) + 3) + 4
    exec(src[start:end], ns)  # noqa: S102 - our own repo's source at a pinned commit
    return ns["COMPETITOR_EXTRACTION_PROMPT"]


ORIGINAL = original_prompt()
FIXED = FIXED_COMPETITOR_EXTRACTION_PROMPT  # candidate fix, kept in eval_sop/, not shipped
NO_SEARCH = "(none — no web search was run for this request)"
OWN_KNOWLEDGE = ("(No search results are available for this request. "
                 "Answer from your own knowledge of the company and its market.)")
ORIGINAL_PROMPT_CONDS = ("a_full", "b_prior", "c_shuffled", "b2_prior_knowledge")


def prompt_for(cond: str) -> str:
    return ORIGINAL if cond in ORIGINAL_PROMPT_CONDS else FIXED


def content_for(cond: str, cid: str, ret: dict, donor_id: str | None) -> str:
    if cond in ("a_full", "d_fixed"):
        return ret[cid]["search_content"]
    if cond == "c_shuffled":
        return ret[donor_id]["search_content"]
    if cond in ("b2_prior_knowledge", "e2_fixed_prior_knowledge"):
        return OWN_KNOWLEDGE
    return NO_SEARCH


def main():
    ap = argparse.ArgumentParser()
    haiku = PROVIDER.name == "anthropic"
    ap.add_argument("--temps", type=float, nargs="+", default=[0.0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--conds", nargs="+",
                    default=["a_full", "b2_prior_knowledge", "c_shuffled", "d_fixed"] if haiku else
                    ["a_full", "b_prior", "c_shuffled", "d_fixed", "e_fixed_prior",
                     "b2_prior_knowledge", "e2_fixed_prior_knowledge"])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the worst-case cost of all uncached calls and exit; refuse if above the cap")
    args = ap.parse_args()
    install_shim()  # the product's analyzer.llm_call now goes through the eval transport
    if haiku and args.seeds != [0]:
        raise SystemExit("Anthropic has no seed parameter; extra seeds would only repeat T=0 calls")
    assert FIXED != ORIGINAL

    comps = [c for c in load_companies() if (RET / f"{c['id']}.json").exists()]
    ret = {c["id"]: json.loads((RET / f"{c['id']}.json").read_text(encoding="utf-8")) for c in comps}
    ids = [c["id"] for c in comps]
    rng = random.Random(0)
    while True:  # derangement: nobody keeps their own evidence
        perm = ids[:]
        rng.shuffle(perm)
        if all(a != b for a, b in zip(ids, perm, strict=True)):
            break
    donor = dict(zip(ids, perm, strict=True))

    out = OUT_DIR / ("discovery_haiku.jsonl" if haiku else "discovery.jsonl")
    done = set()
    for f in [out] if out.exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["id"], r["cond"], r["temperature"], r["seed"], r["model"]))

    tasks = [(temp, seed, cond, c) for temp in args.temps for seed in args.seeds
             for cond in args.conds for c in comps]
    if args.dry_run:
        worst, n_uncached = 0.0, 0
        for temp, seed, cond, c in tasks:
            if (c["id"], cond, temp, seed, MODEL) in done:
                continue
            src = c["id"] if cond in ("a_full", "d_fixed") else donor[c["id"]] if cond == "c_shuffled" else None
            user = (f"The company being researched is: {c['name']}\n\n"   # analyzer.py builds exactly this
                    f"Search results:\n\n{content_for(cond, c['id'], ret, src)}")
            shim.seed = seed
            if shim.key(prompt_for(cond), user, temp) in shim.cache:
                continue
            n_uncached += 1
            worst += shim.worst_case(prompt_for(cond), user)
        total = shim.spent() + worst
        print(f"model={MODEL} provider={PROVIDER.name} tasks={len(tasks)} uncached={n_uncached}")
        print(f"already spent ${shim.spent():.4f}; worst case for uncached calls ${worst:.4f}; "
              f"worst-case total ${total:.4f}; cap ${DEFAULT_CAP:.2f}")
        if PROVIDER.ledger is not None and total > DEFAULT_CAP:
            raise SystemExit("REFUSED: worst case exceeds the cap")
        print("OK: within cap")
        return

    for temp, seed, cond, c in tasks:
        key = (c["id"], cond, temp, seed, MODEL)
        if key in done:
            continue
        src = c["id"] if cond in ("a_full", "d_fixed") else donor[c["id"]] if cond == "c_shuffled" else None
        content, prompt = content_for(cond, c["id"], ret, src), prompt_for(cond)
        analyzer.COMPETITOR_EXTRACTION_PROMPT = prompt
        shim.seed, shim.tag = seed, f"{cond}:{c['id']}"
        # the product hardcodes temperature=0.0 for this step
        shim.force_temperature = temp
        try:
            preds = analyzer.extract_competitors_from_search(c["name"], content, model=MODEL)
        finally:
            shim.force_temperature = None
        rec = {"id": c["id"], "name": c["name"], "tier": c["tier"], "cond": cond,
               "temperature": temp, "seed": seed, "evidence_from": src,
               "model": MODEL, "predictions": preds}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{cond:14s} T={temp} s={seed} {c['name'][:28]:28s} -> "
              f"{[p['name'] for p in preds][:6]}", flush=True)


if __name__ == "__main__":
    main()
