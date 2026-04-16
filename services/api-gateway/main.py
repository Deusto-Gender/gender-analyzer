"""API Gateway / Orchestrator v6"""
import os, json, asyncio, logging
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WBA API Gateway v6", version="6.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WIKI_SVC = os.getenv("WIKI_SERVICE_URL", "http://wikipedia-extractor:8001")
NLP_SVC  = os.getenv("NLP_SERVICE_URL",  "http://nlp-analyzer:8002")
LLM_SVC  = os.getenv("LLM_SERVICE_URL",  "http://llm-auditor:8003")

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
DATA_DIR   = Path("/app/data")
DATA_DIR.mkdir(exist_ok=True)
RESULTS_FILE = DATA_DIR / "results.json"
STATUS_FILE  = DATA_DIR / "status.json"


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


async def wiki_extract(client, nombre, genero, wiki_hint, area) -> Dict:
    try:
        r = await client.post(f"{WIKI_SVC}/extract", json={
            "nombre": nombre, "genero": genero,
            "wiki_hint": wiki_hint, "area": area
        }, timeout=60)
        return r.json()
    except Exception as e:
        return {"nombre": nombre, "genero": genero,
                "exists_in_wikipedia": False, "error": str(e)}


async def nlp_analyze(client, nombre, genero, text, links, cats) -> Dict:
    try:
        r = await client.post(f"{NLP_SVC}/analyze", json={
            "nombre": nombre, "genero": genero,
            "text": text, "links": links, "categories": cats
        }, timeout=120)
        return r.json()
    except Exception as e:
        return {"nombre": nombre, "genero": genero, "error": str(e)}


async def llm_audit_pair(client, pair, wiki_w, wiki_m, nlp_w, nlp_m) -> Dict:
    try:
        r = await client.post(f"{LLM_SVC}/audit", json={
            "pair_id": pair["pair_id"],
            "woman_name": pair["woman"],
            "man_name": pair["man"],
            "woman_text": (wiki_w.get("raw_text") or "")[:5000],
            "man_text":   (wiki_m.get("raw_text") or "")[:5000],
            "area": pair["area"],
            "nlp_woman": nlp_w,
            "nlp_man": nlp_m,
            "wiki_woman": {k: wiki_w.get(k) for k in
                           ["word_count", "num_references", "num_internal_links", "num_categories"]},
            "wiki_man":   {k: wiki_m.get(k) for k in
                           ["word_count", "num_references", "num_internal_links", "num_categories"]},
        }, timeout=300)
        return r.json()
    except Exception as e:
        return {"pair_id": pair["pair_id"], "error": str(e)}


async def run_pipeline(run_llm: bool = False):
    pairs = load_pairs()
    save_status({"status": "running", "progress": 0, "pairs_analyzed": 0,
                 "total_pairs": len(pairs), "current_step": "Iniciando...",
                 "started_at": datetime.now().isoformat()})

    results, valid, skipped = [], 0, 0

    async with httpx.AsyncClient() as client:
        for i, pair in enumerate(pairs):
            progress = round((i / max(len(pairs), 1)) * 100, 1)
            save_status({
                "status": "running", "progress": progress,
                "pairs_analyzed": i, "total_pairs": len(pairs),
                "current_step": f"Wikipedia: {pair['woman']} / {pair['man']}",
                "current_pair": pair["pair_id"]
            })

            wiki_w, wiki_m = await asyncio.gather(
                wiki_extract(client, pair["woman"], "M",
                             pair.get("woman_wiki_hint"), pair.get("area")),
                wiki_extract(client, pair["man"], "H",
                             pair.get("man_wiki_hint"), pair.get("area"))
            )

            both = (wiki_w.get("exists_in_wikipedia") and
                    wiki_m.get("exists_in_wikipedia"))

            skip_parts = []
            if not wiki_w.get("exists_in_wikipedia"):
                skip_parts.append(f"{pair['woman']}: {wiki_w.get('error','no encontrada')}")
            if not wiki_m.get("exists_in_wikipedia"):
                skip_parts.append(f"{pair['man']}: {wiki_m.get('error','no encontrado')}")

            pr = {
                "pair_id": pair["pair_id"],
                "woman_name": pair["woman"],
                "man_name": pair["man"],
                "area": pair["area"],
                "country": pair.get("country", ""),
                "both_in_wikipedia": both,
                "wiki_woman": wiki_w, "wiki_man": wiki_m,
                "nlp_woman": None, "nlp_man": None, "llm_audit": None,
                "skipped": not both,
                "skip_reason": " | ".join(skip_parts)
            }

            if not both:
                skipped += 1
                results.append(pr)
                save_results(results)
                continue

            valid += 1
            save_status({
                "status": "running", "progress": progress + 1,
                "pairs_analyzed": i, "total_pairs": len(pairs),
                "current_step": f"NLP: {pair['woman']} / {pair['man']}",
                "current_pair": pair["pair_id"]
            })

            nlp_w, nlp_m = await asyncio.gather(
                nlp_analyze(client, pair["woman"], "M",
                            wiki_w.get("raw_text", ""),
                            wiki_w.get("links", []), wiki_w.get("categories", [])),
                nlp_analyze(client, pair["man"], "H",
                            wiki_m.get("raw_text", ""),
                            wiki_m.get("links", []), wiki_m.get("categories", []))
            )
            pr["nlp_woman"] = nlp_w
            pr["nlp_man"]   = nlp_m

            if run_llm:
                save_status({
                    "status": "running", "progress": progress + 2,
                    "pairs_analyzed": i, "total_pairs": len(pairs),
                    "current_step": f"LLM audit: par {pair['pair_id']}",
                    "current_pair": pair["pair_id"]
                })
                pr["llm_audit"] = await llm_audit_pair(
                    client, pair, wiki_w, wiki_m, nlp_w, nlp_m)

            results.append(pr)
            save_results(results)
            await asyncio.sleep(0.3)

    save_status({
        "status": "completed", "progress": 100,
        "pairs_analyzed": len(pairs), "total_pairs": len(pairs),
        "valid_pairs": valid, "skipped_pairs": skipped,
        "current_step": "Completado",
        "completed_at": datetime.now().isoformat()
    })


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as c:
        svcs = {}
        for name, url in [("wikipedia", WIKI_SVC), ("nlp", NLP_SVC), ("llm", LLM_SVC)]:
            try:
                r = await c.get(f"{url}/health")
                svcs[name] = {"status": "ok", **r.json()}
            except:
                svcs[name] = {"status": "unavailable"}
    return {"gateway": "ok", "version": "6.0.0", "services": svcs}


@app.get("/config/pairs")
def get_pairs():
    pairs = load_pairs()
    return {"pairs": pairs, "total": len(pairs), "source": "config/pairs.json"}


@app.post("/analyze/start")
async def start(background_tasks: BackgroundTasks, run_llm: bool = False):
    if load_status().get("status") == "running":
        raise HTTPException(409, "Analysis already running")
    pairs = load_pairs()
    background_tasks.add_task(run_pipeline, run_llm)
    return {"message": "Analysis started", "run_llm": run_llm,
            "total_pairs": len(pairs)}


@app.post("/analyze/pair/{pair_id}")
async def analyze_one(pair_id: int, run_llm: bool = False):
    pairs = load_pairs()
    pair = next((p for p in pairs if p["pair_id"] == pair_id), None)
    if not pair:
        raise HTTPException(404, f"Pair {pair_id} not found")
    async with httpx.AsyncClient() as client:
        wiki_w, wiki_m = await asyncio.gather(
            wiki_extract(client, pair["woman"], "M",
                         pair.get("woman_wiki_hint"), pair.get("area")),
            wiki_extract(client, pair["man"], "H",
                         pair.get("man_wiki_hint"), pair.get("area"))
        )
        both = (wiki_w.get("exists_in_wikipedia") and wiki_m.get("exists_in_wikipedia"))
        result = {
            "pair_id": pair_id, "woman_name": pair["woman"],
            "man_name": pair["man"], "area": pair["area"],
            "both_in_wikipedia": both,
            "wiki_woman": wiki_w, "wiki_man": wiki_m,
            "nlp_woman": None, "nlp_man": None, "llm_audit": None
        }
        if both:
            nlp_w, nlp_m = await asyncio.gather(
                nlp_analyze(client, pair["woman"], "M",
                            wiki_w.get("raw_text",""),
                            wiki_w.get("links",[]), wiki_w.get("categories",[])),
                nlp_analyze(client, pair["man"], "H",
                            wiki_m.get("raw_text",""),
                            wiki_m.get("links",[]), wiki_m.get("categories",[]))
            )
            result["nlp_woman"] = nlp_w
            result["nlp_man"]   = nlp_m
            if run_llm:
                result["llm_audit"] = await llm_audit_pair(
                    client, pair, wiki_w, wiki_m, nlp_w, nlp_m)
    return result


@app.get("/analyze/status")
def status(): return load_status()

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
    all_r = load_results()
    valid = [r for r in all_r if r.get("both_in_wikipedia") and not r.get("skipped")]
    def avg(lst): return round(sum(lst)/len(lst), 4) if lst else 0
    def sg(r, k1, k2, d=0):
        try: return float(r.get(k1,{}).get(k2, d) or d)
        except: return d
    return {
        "total_pairs": len(load_pairs()),
        "analyzed_pairs": len(all_r),
        "valid_pairs": len(valid),
        "skipped_pairs": len(all_r) - len(valid),
        "wikipedia": {
            "avg_word_count_women":  avg([sg(r,"wiki_woman","word_count") for r in valid]),
            "avg_word_count_men":    avg([sg(r,"wiki_man","word_count") for r in valid]),
            "avg_references_women":  avg([sg(r,"wiki_woman","num_references") for r in valid]),
            "avg_references_men":    avg([sg(r,"wiki_man","num_references") for r in valid]),
            "avg_links_women":       avg([sg(r,"wiki_woman","num_internal_links") for r in valid]),
            "avg_links_men":         avg([sg(r,"wiki_man","num_internal_links") for r in valid]),
            "avg_categories_women":  avg([sg(r,"wiki_woman","num_categories") for r in valid]),
            "avg_categories_men":    avg([sg(r,"wiki_man","num_categories") for r in valid]),
        },
        "nlp": {
            "avg_domesticity_women":       avg([sg(r,"nlp_woman","domesticity_index") for r in valid if r.get("nlp_woman")]),
            "avg_domesticity_men":         avg([sg(r,"nlp_man","domesticity_index") for r in valid if r.get("nlp_man")]),
            "avg_epistemic_density_women": avg([sg(r,"nlp_woman","epistemic_density") for r in valid if r.get("nlp_woman")]),
            "avg_epistemic_density_men":   avg([sg(r,"nlp_man","epistemic_density") for r in valid if r.get("nlp_man")]),
            "avg_agency_ratio_women":      avg([sg(r,"nlp_woman","agency_ratio") for r in valid if r.get("nlp_woman")]),
            "avg_agency_ratio_men":        avg([sg(r,"nlp_man","agency_ratio") for r in valid if r.get("nlp_man")]),
            "avg_sci_links_women":         avg([sg(r,"nlp_woman","scientific_links_ratio") for r in valid if r.get("nlp_woman")]),
            "avg_sci_links_men":           avg([sg(r,"nlp_man","scientific_links_ratio") for r in valid if r.get("nlp_man")]),
        },
        "llm": {
            "avg_bias_score_women": avg([r["llm_audit"]["bias_score_woman"] for r in valid if r.get("llm_audit") and not r["llm_audit"].get("error")]),
            "avg_bias_score_men":   avg([r["llm_audit"]["bias_score_man"]   for r in valid if r.get("llm_audit") and not r["llm_audit"].get("error")]),
        }
    }

@app.delete("/results")
def clear():
    if RESULTS_FILE.exists(): RESULTS_FILE.unlink()
    save_status({"status": "idle", "progress": 0})
    return {"message": "Cleared"}

@app.delete("/cache")
async def clear_cache():
    async with httpx.AsyncClient(timeout=10) as c:
        try: await c.delete(f"{WIKI_SVC}/cache")
        except: pass
    return {"message": "Cache cleared"}
