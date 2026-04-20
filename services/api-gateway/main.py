"""API Gateway / Orchestrator v6 — fixed"""
import os, json, asyncio, logging, time as _time
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WBA API Gateway v6", version="6.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WIKI_SVC = os.getenv("WIKI_SERVICE_URL", "http://wikipedia-extractor:8001")
NLP_SVC  = os.getenv("NLP_SERVICE_URL",  "http://nlp-analyzer:8002")
LLM_SVC  = os.getenv("LLM_SERVICE_URL",  "http://llm-auditor:8003")

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
DATA_DIR   = Path("/app/data")
DATA_DIR.mkdir(exist_ok=True)
RESULTS_FILE = DATA_DIR / "results.json"
STATUS_FILE  = DATA_DIR / "status.json"


# ── Persistence helpers ────────────────────────────────────────────────────────

def load_pairs() -> List[Dict]:
    p = CONFIG_DIR / "pairs.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("pairs", [])
    logger.warning(f"pairs.json not found at {p}")
    return []

def save_status(s: Dict):
    STATUS_FILE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")

def load_status() -> Dict:
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {"status": "idle", "progress": 0, "pairs_analyzed": 0, "total_pairs": 0}

def save_results(r: List[Dict]):
    RESULTS_FILE.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

def load_results() -> List[Dict]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


# ── Service call helpers ───────────────────────────────────────────────────────

async def clear_wiki_cache(client: httpx.AsyncClient):
    """Clear Wikipedia extractor cache before fresh extraction."""
    try:
        r = await client.delete(f"{WIKI_SVC}/cache", timeout=15)
        logger.info(f"Cache cleared: {r.json()}")
    except Exception as e:
        logger.warning(f"Cache clear failed (non-fatal): {e}")


async def wiki_extract(client, nombre, genero, wiki_hint, area) -> Dict:
    try:
        r = await client.post(f"{WIKI_SVC}/extract", json={
            "nombre": nombre, "genero": genero,
            "wiki_hint": wiki_hint, "area": area
        }, timeout=90)
        return r.json()
    except Exception as e:
        logger.error(f"Wiki extract failed for {nombre}: {e}")
        return {"nombre": nombre, "genero": genero,
                "exists_in_wikipedia": False, "error": str(e)}


async def nlp_analyze(client, nombre, genero, text, links, cats) -> Dict:
    try:
        r = await client.post(f"{NLP_SVC}/analyze", json={
            "nombre": nombre, "genero": genero,
            "text": text, "links": links, "categories": cats
        }, timeout=180)
        return r.json()
    except Exception as e:
        logger.error(f"NLP analyze failed for {nombre}: {e}")
        return {"nombre": nombre, "genero": genero, "error": str(e)}


async def llm_audit_pair(client, pair, wiki_w, wiki_m, nlp_w, nlp_m) -> Dict:
    """
    Run the full LLM-as-a-Judge audit for one pair.
    Timeout is long: 8 Claude API calls × ~15s each = ~120s minimum per pair.
    """
    try:
        r = await client.post(f"{LLM_SVC}/audit", json={
            "pair_id":    pair["pair_id"],
            "woman_name": pair["woman"],
            "man_name":   pair["man"],
            "woman_text": (wiki_w.get("raw_text") or "")[:6000],
            "man_text":   (wiki_m.get("raw_text") or "")[:6000],
            "area":       pair["area"],
            "nlp_woman":  nlp_w,
            "nlp_man":    nlp_m,
            "wiki_woman": {k: wiki_w.get(k) for k in
                           ["word_count", "num_references", "num_internal_links",
                            "num_categories", "wikipedia_url", "wikipedia_title"]},
            "wiki_man":   {k: wiki_m.get(k) for k in
                           ["word_count", "num_references", "num_internal_links",
                            "num_categories", "wikipedia_url", "wikipedia_title"]},
        }, timeout=600)   # 10 min: 12 pairs × 8 Claude calls × ~15s
        data = r.json()
        if "error" in data and data["error"]:
            logger.error(f"LLM audit pair {pair['pair_id']} returned error: {data['error']}")
        else:
            logger.info(f"LLM audit OK for pair {pair['pair_id']}")
        return data
    except Exception as e:
        logger.error(f"LLM audit HTTP failed for pair {pair['pair_id']}: {e}")
        return {"pair_id": pair["pair_id"], "error": str(e),
                "woman_name": pair["woman"], "man_name": pair["man"]}


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def process_pair(client: httpx.AsyncClient, pair: Dict,
                       run_llm: bool, semaphore: asyncio.Semaphore,
                       results: List, counter: Dict):
    """
    Process a single pair concurrently.
    Semaphore limits concurrent Wikipedia requests to respect rate limits.
    """
    async with semaphore:
        pair_id = pair["pair_id"]
        logger.info(f"Start pair {pair_id}: {pair['woman']} / {pair['man']}")

        # Wikipedia: woman + man in parallel (already was parallel)
        wiki_w, wiki_m = await asyncio.gather(
            wiki_extract(client, pair["woman"], "M",
                         pair.get("woman_wiki_hint"), pair.get("area")),
            wiki_extract(client, pair["man"],   "H",
                         pair.get("man_wiki_hint"),   pair.get("area"))
        )

        both = (wiki_w.get("exists_in_wikipedia") and
                wiki_m.get("exists_in_wikipedia"))

        skip_parts = []
        if not wiki_w.get("exists_in_wikipedia"):
            skip_parts.append(f"{pair['woman']}: {wiki_w.get('error','no encontrada')}")
        if not wiki_m.get("exists_in_wikipedia"):
            skip_parts.append(f"{pair['man']}: {wiki_m.get('error','no encontrado')}")

        pr = {
            "pair_id":           pair_id,
            "woman_name":        pair["woman"],
            "man_name":          pair["man"],
            "area":              pair["area"],
            "country":           pair.get("country", ""),
            "both_in_wikipedia": both,
            "wiki_woman":        wiki_w,
            "wiki_man":          wiki_m,
            "nlp_woman":         None,
            "nlp_man":           None,
            "llm_audit":         None,
            "skipped":           not both,
            "skip_reason":       " | ".join(skip_parts)
        }

        if both:
            # NLP: woman + man in parallel
            nlp_w, nlp_m = await asyncio.gather(
                nlp_analyze(client, pair["woman"], "M",
                            wiki_w.get("raw_text", ""),
                            wiki_w.get("links", []),
                            wiki_w.get("categories", [])),
                nlp_analyze(client, pair["man"],   "H",
                            wiki_m.get("raw_text", ""),
                            wiki_m.get("links", []),
                            wiki_m.get("categories", []))
            )
            pr["nlp_woman"] = nlp_w
            pr["nlp_man"]   = nlp_m

            if run_llm:
                pr["llm_audit"] = await llm_audit_pair(
                    client, pair, wiki_w, wiki_m, nlp_w, nlp_m)

        # Thread-safe result accumulation
        results.append(pr)
        save_results(sorted(results, key=lambda x: x["pair_id"]))

        counter["done"] += 1
        if both:
            counter["valid"] += 1
        else:
            counter["skipped"] += 1

        logger.info(f"Done pair {pair_id} ({counter['done']}/{counter['total']})")


def _status_with_timing(base: Dict, t0: float, done: int) -> Dict:
    """Add elapsed time and avg-per-pair to any status dict."""
    elapsed = round(_time.monotonic() - t0)
    avg = round(elapsed / done, 1) if done > 0 else 0
    return {**base,
            "elapsed_seconds": elapsed,
            "avg_seconds_per_pair": avg}


async def run_pipeline(run_llm: bool = False):
    """
    Full pipeline: Wikipedia + NLP [+ LLM if run_llm=True].
    Always clears cache and re-extracts everything fresh.
    """
    pairs = load_pairs()
    t0 = _time.monotonic()
    started_at = datetime.now().isoformat()

    save_status(_status_with_timing({
        "status": "running", "progress": 0, "pairs_analyzed": 0,
        "total_pairs": len(pairs), "current_step": "Iniciando...",
        "run_llm": run_llm, "started_at": started_at,
        "phase": "wikipedia+nlp" + ("+llm" if run_llm else ""),
    }, t0, 0))

    results: List[Dict] = []
    counter = {"done": 0, "valid": 0, "skipped": 0, "total": len(pairs)}

    async with httpx.AsyncClient() as client:

        save_status(_status_with_timing({
            "status": "running", "progress": 0, "pairs_analyzed": 0,
            "total_pairs": len(pairs),
            "current_step": "Limpiando caché Wikipedia...",
            "run_llm": run_llm, "started_at": started_at,
            "phase": "cache_clear",
        }, t0, 0))
        await clear_wiki_cache(client)

        wiki_sem = asyncio.Semaphore(4)

        async def update_status():
            while counter["done"] < len(pairs):
                done = counter["done"]
                pct  = round(done / max(len(pairs), 1) * 100, 0)
                save_status(_status_with_timing({
                    "status": "running",
                    "progress": pct,
                    "pairs_analyzed": done,
                    "total_pairs": len(pairs),
                    "valid_pairs": counter["valid"],
                    "current_step": f"Wikipedia+NLP: {done}/{len(pairs)} pares completados",
                    "run_llm": run_llm,
                    "started_at": started_at,
                    "phase": "wikipedia+nlp",
                }, t0, done))
                await asyncio.sleep(2)

        status_task = asyncio.create_task(update_status())

        await asyncio.gather(*[
            process_pair(client, pair, run_llm, wiki_sem, results, counter)
            for pair in pairs
        ])

        status_task.cancel()
        try: await status_task
        except asyncio.CancelledError: pass

    elapsed = round(_time.monotonic() - t0)
    avg = round(elapsed / max(counter["valid"] + counter["skipped"], 1), 1)
    save_status({
        "status": "completed", "progress": 100,
        "pairs_analyzed": len(pairs), "total_pairs": len(pairs),
        "valid_pairs": counter["valid"], "skipped_pairs": counter["skipped"],
        "run_llm": run_llm,
        "current_step": "Completado",
        "completed_at": datetime.now().isoformat(),
        "started_at": started_at,
        "elapsed_seconds": elapsed,
        "avg_seconds_per_pair": avg,
        "phase": "completed",
    })
    logger.info(f"Pipeline done in {elapsed}s: {counter['valid']} valid, avg {avg}s/par")


async def run_pipeline_llm_only():
    """
    LLM-only pass: reuses existing Wikipedia+NLP results.
    Does NOT clear cache or re-extract — only adds llm_audit to each valid pair.
    """
    existing = load_results()
    valid_pairs = [r for r in existing if r.get("both_in_wikipedia") and not r.get("skipped")]
    pairs_cfg   = {p["pair_id"]: p for p in load_pairs()}

    if not valid_pairs:
        save_status({"status": "idle", "current_step":
                     "Sin pares válidos previos. Ejecuta Wikipedia+NLP primero.",
                     "elapsed_seconds": 0, "avg_seconds_per_pair": 0})
        return

    t0 = _time.monotonic()
    started_at = datetime.now().isoformat()
    total = len(valid_pairs)
    counter = {"done": 0, "total": total}

    save_status(_status_with_timing({
        "status": "running", "progress": 0, "pairs_analyzed": 0,
        "total_pairs": total,
        "current_step": f"Auditoría LLM sobre {total} pares ya extraídos (sin re-extraer Wikipedia/NLP)...",
        "run_llm": True, "started_at": started_at, "phase": "llm_only",
    }, t0, 0))

    async with httpx.AsyncClient() as client:
        llm_sem = asyncio.Semaphore(1)  # sequential LLM audits — each does 3 parallel Claude calls internally

        async def audit_one(pr: Dict):
            pair_id = pr["pair_id"]
            pair_cfg = pairs_cfg.get(pair_id, {})
            async with llm_sem:
                logger.info(f"LLM-only audit pair {pair_id}")
                audit = await llm_audit_pair(
                    client, pair_cfg,
                    pr.get("wiki_woman") or {},
                    pr.get("wiki_man") or {},
                    pr.get("nlp_woman") or {},
                    pr.get("nlp_man") or {}
                )
                pr["llm_audit"] = audit
                counter["done"] += 1
                done = counter["done"]
                pct = round(done / total * 100, 0)
                save_status(_status_with_timing({
                    "status": "running", "progress": pct,
                    "pairs_analyzed": done, "total_pairs": total,
                    "current_step": f"LLM audit: {done}/{total} pares",
                    "run_llm": True, "started_at": started_at, "phase": "llm_only",
                }, t0, done))

        await asyncio.gather(*[audit_one(pr) for pr in valid_pairs])

    # Merge audited results back
    audited = {pr["pair_id"]: pr for pr in valid_pairs}
    merged = [audited.get(r["pair_id"], r) for r in existing]
    save_results(merged)

    elapsed = round(_time.monotonic() - t0)
    avg = round(elapsed / max(counter["done"], 1), 1)
    save_status({
        "status": "completed", "progress": 100,
        "pairs_analyzed": total, "total_pairs": total,
        "run_llm": True,
        "current_step": "Auditoría LLM completada",
        "completed_at": datetime.now().isoformat(),
        "started_at": started_at,
        "elapsed_seconds": elapsed,
        "avg_seconds_per_pair": avg,
        "phase": "llm_only_completed",
    })
    logger.info(f"LLM-only done in {elapsed}s: {counter['done']} pairs, avg {avg}s/par")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as c:
        svcs = {}
        for name, url in [("wikipedia", WIKI_SVC), ("nlp", NLP_SVC), ("llm", LLM_SVC)]:
            try:
                r = await c.get(f"{url}/health")
                svcs[name] = {"status": "ok", **r.json()}
            except Exception as e:
                svcs[name] = {"status": "unavailable", "error": str(e)}
    return {"gateway": "ok", "version": "6.1.0", "services": svcs}


@app.get("/config/pairs")
def get_pairs():
    pairs = load_pairs()
    return {"pairs": pairs, "total": len(pairs), "source": "config/pairs.json"}


@app.post("/analyze/start")
async def start(background_tasks: BackgroundTasks,
                run_llm: bool = False,
                force_reextract: bool = False):
    """
    Start analysis pipeline.

    Behaviour:
      run_llm=false                          → full Wikipedia+NLP (clears & re-extracts)
      run_llm=true, existing results present → LLM-only (reuses Wikipedia+NLP, no re-extract)
      run_llm=true, no previous results      → full pipeline incl. LLM
      force_reextract=true                   → always clears and re-extracts everything
    """
    if load_status().get("status") == "running":
        raise HTTPException(409, "Analysis already running")

    pairs      = load_pairs()
    has_wiki   = RESULTS_FILE.exists() and any(
        r.get("both_in_wikipedia")
        for r in load_results()
    )

    if run_llm and has_wiki and not force_reextract:
        # Reuse existing Wikipedia+NLP — only run LLM audit
        background_tasks.add_task(run_pipeline_llm_only)
        return {"message": "LLM audit started (reusing existing Wikipedia+NLP results)",
                "mode": "llm_only", "run_llm": True,
                "total_pairs": len([r for r in load_results()
                                    if r.get("both_in_wikipedia")])}
    else:
        # Full pipeline from scratch
        if RESULTS_FILE.exists():
            RESULTS_FILE.unlink()
        save_status({"status": "idle", "progress": 0})
        background_tasks.add_task(run_pipeline, run_llm)
        mode = "full_with_llm" if run_llm else "wikipedia_nlp_only"
        return {"message": "Analysis started", "mode": mode,
                "run_llm": run_llm, "total_pairs": len(pairs)}


@app.get("/analyze/status")
def status():
    return load_status()


@app.get("/results")
def get_results():
    r = load_results()
    return {"results": r, "count": len(r)}


@app.get("/results/valid")
def valid_results():
    r = [x for x in load_results() if x.get("both_in_wikipedia") and not x.get("skipped")]
    return {"results": r, "count": len(r)}


@app.get("/results/skipped")
def skipped_results():
    r = [x for x in load_results() if x.get("skipped") or not x.get("both_in_wikipedia")]
    return {"results": r, "count": len(r)}


@app.get("/results/summary")
def summary():
    all_r  = load_results()
    valid  = [r for r in all_r if r.get("both_in_wikipedia") and not r.get("skipped")]

    def avg(lst):
        lst = [x for x in lst if x is not None]
        return round(sum(lst) / len(lst), 4) if lst else 0

    def sg(r, k1, k2, d=0):
        try:   return float(r.get(k1, {}).get(k2, d) or d)
        except: return d

    # LLM scores — support both old field names and new v6.1 field names
    def llm_score_w(r):
        a = r.get("llm_audit") or {}
        return float(a.get("bias_score_wiki_woman") or a.get("bias_score_woman") or 0)

    def llm_score_m(r):
        a = r.get("llm_audit") or {}
        return float(a.get("bias_score_wiki_man") or a.get("bias_score_man") or 0)

    llm_valid = [r for r in valid
                 if r.get("llm_audit") and not r["llm_audit"].get("error")]

    return {
        "total_pairs":    len(load_pairs()),
        "analyzed_pairs": len(all_r),
        "valid_pairs":    len(valid),
        "skipped_pairs":  len(all_r) - len(valid),
        "wikipedia": {
            "avg_word_count_women":  avg([sg(r,"wiki_woman","word_count") for r in valid]),
            "avg_word_count_men":    avg([sg(r,"wiki_man",  "word_count") for r in valid]),
            "avg_references_women":  avg([sg(r,"wiki_woman","num_references") for r in valid]),
            "avg_references_men":    avg([sg(r,"wiki_man",  "num_references") for r in valid]),
            "avg_links_women":       avg([sg(r,"wiki_woman","num_internal_links") for r in valid]),
            "avg_links_men":         avg([sg(r,"wiki_man",  "num_internal_links") for r in valid]),
            "avg_categories_women":  avg([sg(r,"wiki_woman","num_categories") for r in valid]),
            "avg_categories_men":    avg([sg(r,"wiki_man",  "num_categories") for r in valid]),
        },
        "nlp": {
            "avg_domesticity_women":       avg([sg(r,"nlp_woman","domesticity_index")    for r in valid if r.get("nlp_woman")]),
            "avg_domesticity_men":         avg([sg(r,"nlp_man",  "domesticity_index")    for r in valid if r.get("nlp_man")]),
            "avg_epistemic_density_women": avg([sg(r,"nlp_woman","epistemic_density")    for r in valid if r.get("nlp_woman")]),
            "avg_epistemic_density_men":   avg([sg(r,"nlp_man",  "epistemic_density")    for r in valid if r.get("nlp_man")]),
            "avg_agency_ratio_women":      avg([sg(r,"nlp_woman","agency_ratio")         for r in valid if r.get("nlp_woman")]),
            "avg_agency_ratio_men":        avg([sg(r,"nlp_man",  "agency_ratio")         for r in valid if r.get("nlp_man")]),
            "avg_sci_links_women":         avg([sg(r,"nlp_woman","scientific_links_ratio") for r in valid if r.get("nlp_woman")]),
            "avg_sci_links_men":           avg([sg(r,"nlp_man",  "scientific_links_ratio") for r in valid if r.get("nlp_man")]),
        },
        "llm": {
            "avg_bias_score_women": avg([llm_score_w(r) for r in llm_valid]),
            "avg_bias_score_men":   avg([llm_score_m(r) for r in llm_valid]),
        }
    }


@app.delete("/results")
def clear_results():
    if RESULTS_FILE.exists():
        RESULTS_FILE.unlink()
    save_status({"status": "idle", "progress": 0})
    return {"message": "Results cleared"}



@app.get("/llm/test")
async def test_llm():
    """Proxy to llm-auditor test endpoint — verifies API key validity."""
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.get(f"{LLM_SVC}/audit/test")
            return r.json()
        except Exception as e:
            return {"ok": False, "error": f"No se puede conectar al llm-auditor: {str(e)}",
                    "fix": "Verifica que el contenedor wba-llm-auditor está corriendo: docker ps"}


@app.delete("/cache")
async def clear_cache():
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.delete(f"{WIKI_SVC}/cache")
            return {"message": "Cache cleared", "detail": r.json()}
        except Exception as e:
            return {"message": "Cache clear failed", "error": str(e)}
