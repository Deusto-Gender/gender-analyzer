"""
API Gateway / Orchestrator Microservice
Coordinates all other services and exposes the unified API.
Manages the full analysis pipeline for biography pairs.
"""
import os
import json
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Wikipedia Bias Analyzer - API Gateway",
    description="Orchestrates bias analysis pipeline for biography pairs",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Service URLs
WIKI_SVC = os.getenv("WIKI_SERVICE_URL", "http://wikipedia-extractor:8001")
NLP_SVC = os.getenv("NLP_SERVICE_URL", "http://nlp-analyzer:8002")
LLM_SVC = os.getenv("LLM_SERVICE_URL", "http://llm-auditor:8003")

RESULTS_FILE = "/app/data/results.json"
STATUS_FILE = "/app/data/status.json"
os.makedirs("/app/data", exist_ok=True)

BIOGRAPHY_PAIRS = [
    {"pair_id": 1, "woman": "Montserrat Meya", "man": "Ramón López de Mántaras", "area": "Lingüística computacional / IA"},
    {"pair_id": 2, "woman": "Asunción Gómez-Pérez", "man": "Carles Sierra", "area": "Web semántica / Ontologías"},
    {"pair_id": 3, "woman": "Nuria Oliver", "man": "Mateo Valero", "area": "IA / Big Data / Supercomputación"},
    {"pair_id": 4, "woman": "Regina Llopis Rivas", "man": "Andrés Pedreño", "area": "IA aplicada / Economía digital"},
    {"pair_id": 5, "woman": "María Ángeles Martín Prats", "man": "Pedro Duque", "area": "Ingeniería aeroespacial"},
    {"pair_id": 6, "woman": "Concha Monje", "man": "José Luis Pons", "area": "Robótica"},
    {"pair_id": 7, "woman": "Laura Lechuga", "man": "Luis Liz-Marzán", "area": "Nanociencia / Biosensores"},
    {"pair_id": 8, "woman": "Elena García Armada", "man": "José Luis López Gómez", "area": "Exoesqueletos / Ingeniería"},
    {"pair_id": 9, "woman": "Lourdes Verdes-Montenegro", "man": "José Cernicharo", "area": "Radioastronomía / Astrofísica"},
    {"pair_id": 10, "woman": "María José Escalona", "man": "Manuel Hermenegildo", "area": "Ingeniería del software"},
    {"pair_id": 11, "woman": "Julia G. Niso", "man": "Gustavo Deco", "area": "Neuroingeniería / Neurociencia computacional"},
    {"pair_id": 12, "woman": "Sara García Alonso", "man": "Pedro Duque", "area": "Biología molecular / Astronáutica"},
    {"pair_id": 13, "woman": "Silvia Nair Goyanes", "man": "Juan Martín Maldacena", "area": "Física"},
    {"pair_id": 14, "woman": "Noemí Zaritzky", "man": "Lino Barañao", "area": "Ingeniería química / Bioquímica"},
    {"pair_id": 15, "woman": "Raquel Lía Chan", "man": "Esteban Hopp", "area": "Biotecnología vegetal"},
    {"pair_id": 16, "woman": "Barbarita Lara", "man": "Claudio Gutiérrez", "area": "Informática / Sistemas de comunicación"},
    {"pair_id": 17, "woman": "Loreto Valenzuela", "man": "Pablo Valenzuela", "area": "Biotecnología de enzimas"},
    {"pair_id": 18, "woman": "Lucía Spangenberg", "man": "Rafael Radi", "area": "Bioinformática / Bioquímica"},
    {"pair_id": 19, "woman": "Fiorella Haim", "man": "Miguel Brechner", "area": "Innovación educativa digital"},
    {"pair_id": 20, "woman": "María Clara Betancourt", "man": "Manuel Elkin Patarroyo", "area": "Ingeniería ambiental / Inmunología"},
]


# ── State Management ───────────────────────────────────────────────────────────

def save_status(status: Dict):
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, ensure_ascii=False)

def load_status() -> Dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {"status": "idle", "progress": 0, "pairs_analyzed": 0, "total_pairs": 0}

def save_results(results: List[Dict]):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def load_results() -> List[Dict]:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []


# ── Pipeline ───────────────────────────────────────────────────────────────────

async def extract_wikipedia(client: httpx.AsyncClient, nombre: str, genero: str) -> Dict:
    try:
        resp = await client.post(
            f"{WIKI_SVC}/extract",
            json={"nombre": nombre, "genero": genero},
            timeout=60
        )
        return resp.json()
    except Exception as e:
        logger.error(f"Wiki extraction error for {nombre}: {e}")
        return {"nombre": nombre, "genero": genero, "exists_in_wikipedia": False, "error": str(e)}


async def analyze_nlp(client: httpx.AsyncClient, nombre: str, genero: str, text: str, links: List, categories: List) -> Dict:
    try:
        resp = await client.post(
            f"{NLP_SVC}/analyze",
            json={"nombre": nombre, "genero": genero, "text": text, "links": links, "categories": categories},
            timeout=120
        )
        return resp.json()
    except Exception as e:
        logger.error(f"NLP analysis error for {nombre}: {e}")
        return {"nombre": nombre, "genero": genero, "error": str(e)}


async def run_llm_audit(client: httpx.AsyncClient, pair: Dict, woman_text: str, man_text: str) -> Dict:
    try:
        resp = await client.post(
            f"{LLM_SVC}/audit",
            json={
                "pair_id": pair["pair_id"],
                "woman_name": pair["woman"],
                "man_name": pair["man"],
                "woman_text": woman_text[:5000],
                "man_text": man_text[:5000],
                "area": pair["area"]
            },
            timeout=180
        )
        return resp.json()
    except Exception as e:
        logger.error(f"LLM audit error for pair {pair['pair_id']}: {e}")
        return {"pair_id": pair["pair_id"], "error": str(e)}


async def analyze_all_pairs(run_llm: bool = False):
    """Full pipeline: Wikipedia extraction → NLP analysis → (optional) LLM audit."""
    save_status({
        "status": "running",
        "progress": 0,
        "pairs_analyzed": 0,
        "total_pairs": len(BIOGRAPHY_PAIRS),
        "current_step": "Iniciando análisis...",
        "started_at": datetime.now().isoformat()
    })

    results = []
    valid_pairs = 0
    skipped_pairs = 0

    async with httpx.AsyncClient() as client:
        for i, pair in enumerate(BIOGRAPHY_PAIRS):
            progress = (i / len(BIOGRAPHY_PAIRS)) * 100
            save_status({
                "status": "running",
                "progress": round(progress, 1),
                "pairs_analyzed": i,
                "total_pairs": len(BIOGRAPHY_PAIRS),
                "current_step": f"Extrayendo Wikipedia: {pair['woman']} / {pair['man']}",
                "current_pair": pair["pair_id"]
            })
            
            logger.info(f"Processing pair {pair['pair_id']}: {pair['woman']} / {pair['man']}")

            # Step 1: Extract Wikipedia data for both
            wiki_woman, wiki_man = await asyncio.gather(
                extract_wikipedia(client, pair["woman"], "M"),
                extract_wikipedia(client, pair["man"], "H")
            )

            # Check if both exist in Wikipedia
            both_exist = (
                wiki_woman.get("exists_in_wikipedia", False) and
                wiki_man.get("exists_in_wikipedia", False)
            )

            pair_result = {
                "pair_id": pair["pair_id"],
                "woman_name": pair["woman"],
                "man_name": pair["man"],
                "area": pair["area"],
                "both_in_wikipedia": both_exist,
                "wiki_woman": wiki_woman,
                "wiki_man": wiki_man,
                "nlp_woman": None,
                "nlp_man": None,
                "llm_audit": None,
                "skipped": not both_exist,
                "skip_reason": ""
            }

            if not both_exist:
                skip_reason = []
                if not wiki_woman.get("exists_in_wikipedia"):
                    skip_reason.append(f"{pair['woman']} no tiene artículo en Wikipedia ES")
                if not wiki_man.get("exists_in_wikipedia"):
                    skip_reason.append(f"{pair['man']} no tiene artículo en Wikipedia ES")
                pair_result["skip_reason"] = "; ".join(skip_reason)
                skipped_pairs += 1
                logger.info(f"Pair {pair['pair_id']} skipped: {pair_result['skip_reason']}")
                results.append(pair_result)
                save_results(results)
                continue

            valid_pairs += 1

            # Step 2: NLP Analysis
            save_status({
                "status": "running",
                "progress": round(progress + 2, 1),
                "pairs_analyzed": i,
                "total_pairs": len(BIOGRAPHY_PAIRS),
                "current_step": f"Análisis NLP: {pair['woman']} / {pair['man']}",
                "current_pair": pair["pair_id"]
            })

            text_woman = wiki_woman.get("raw_text", "") or ""
            text_man = wiki_man.get("raw_text", "") or ""

            nlp_woman, nlp_man = await asyncio.gather(
                analyze_nlp(
                    client, pair["woman"], "M", text_woman,
                    wiki_woman.get("links", []), wiki_woman.get("categories", [])
                ),
                analyze_nlp(
                    client, pair["man"], "H", text_man,
                    wiki_man.get("links", []), wiki_man.get("categories", [])
                )
            )
            
            pair_result["nlp_woman"] = nlp_woman
            pair_result["nlp_man"] = nlp_man

            # Step 3: LLM Audit (optional, requires API key)
            if run_llm and text_woman and text_man:
                save_status({
                    "status": "running",
                    "progress": round(progress + 4, 1),
                    "pairs_analyzed": i,
                    "total_pairs": len(BIOGRAPHY_PAIRS),
                    "current_step": f"Auditoría LLM: par {pair['pair_id']}",
                    "current_pair": pair["pair_id"]
                })
                
                llm_result = await run_llm_audit(client, pair, text_woman, text_man)
                pair_result["llm_audit"] = llm_result

            results.append(pair_result)
            save_results(results)
            await asyncio.sleep(0.5)  # Politeness delay

    save_status({
        "status": "completed",
        "progress": 100,
        "pairs_analyzed": len(BIOGRAPHY_PAIRS),
        "total_pairs": len(BIOGRAPHY_PAIRS),
        "valid_pairs": valid_pairs,
        "skipped_pairs": skipped_pairs,
        "current_step": "Análisis completado",
        "completed_at": datetime.now().isoformat()
    })

    logger.info(f"Analysis complete: {valid_pairs} valid pairs, {skipped_pairs} skipped")
    return results


# ── API Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Check health of all services."""
    async with httpx.AsyncClient(timeout=5) as client:
        services = {}
        for name, url in [("wikipedia", WIKI_SVC), ("nlp", NLP_SVC), ("llm", LLM_SVC)]:
            try:
                r = await client.get(f"{url}/health")
                services[name] = {"status": "ok", **r.json()}
            except:
                services[name] = {"status": "unavailable"}
    return {"gateway": "ok", "services": services}


@app.get("/pairs")
def get_pairs():
    """Get all biography pairs."""
    return {"pairs": BIOGRAPHY_PAIRS, "total": len(BIOGRAPHY_PAIRS)}


@app.post("/analyze/start")
async def start_analysis(background_tasks: BackgroundTasks, run_llm: bool = False):
    """Start the full analysis pipeline in background."""
    status = load_status()
    if status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Analysis already running")
    
    background_tasks.add_task(analyze_all_pairs, run_llm)
    return {
        "message": "Analysis started",
        "run_llm": run_llm,
        "total_pairs": len(BIOGRAPHY_PAIRS)
    }


@app.post("/analyze/pair/{pair_id}")
async def analyze_single_pair(pair_id: int, run_llm: bool = False):
    """Analyze a single pair by ID."""
    pair = next((p for p in BIOGRAPHY_PAIRS if p["pair_id"] == pair_id), None)
    if not pair:
        raise HTTPException(status_code=404, detail=f"Pair {pair_id} not found")

    async with httpx.AsyncClient() as client:
        wiki_woman, wiki_man = await asyncio.gather(
            extract_wikipedia(client, pair["woman"], "M"),
            extract_wikipedia(client, pair["man"], "H")
        )
        
        both_exist = wiki_woman.get("exists_in_wikipedia") and wiki_man.get("exists_in_wikipedia")
        
        result = {
            "pair_id": pair_id,
            "woman_name": pair["woman"],
            "man_name": pair["man"],
            "area": pair["area"],
            "both_in_wikipedia": both_exist,
            "wiki_woman": wiki_woman,
            "wiki_man": wiki_man,
            "nlp_woman": None,
            "nlp_man": None,
            "llm_audit": None
        }
        
        if both_exist:
            text_w = wiki_woman.get("raw_text", "") or ""
            text_m = wiki_man.get("raw_text", "") or ""
            
            nlp_w, nlp_m = await asyncio.gather(
                analyze_nlp(client, pair["woman"], "M", text_w,
                           wiki_woman.get("links", []), wiki_woman.get("categories", [])),
                analyze_nlp(client, pair["man"], "H", text_m,
                           wiki_man.get("links", []), wiki_man.get("categories", []))
            )
            result["nlp_woman"] = nlp_w
            result["nlp_man"] = nlp_m
            
            if run_llm:
                result["llm_audit"] = await run_llm_audit(client, pair, text_w, text_m)

    return result


@app.get("/analyze/status")
def get_status():
    """Get current analysis status."""
    return load_status()


@app.get("/results")
def get_results():
    """Get all analysis results."""
    return {"results": load_results(), "count": len(load_results())}


@app.get("/results/valid")
def get_valid_results():
    """Get only results where both biographies exist in Wikipedia."""
    all_results = load_results()
    valid = [r for r in all_results if r.get("both_in_wikipedia") and not r.get("skipped")]
    return {"results": valid, "count": len(valid)}


@app.get("/results/skipped")
def get_skipped_results():
    """Get pairs that were skipped (one or both not in Wikipedia ES)."""
    all_results = load_results()
    skipped = [r for r in all_results if r.get("skipped") or not r.get("both_in_wikipedia")]
    return {"results": skipped, "count": len(skipped)}


@app.get("/results/summary")
def get_summary():
    """Compute aggregate summary statistics."""
    all_results = load_results()
    valid = [r for r in all_results if r.get("both_in_wikipedia") and not r.get("skipped")]
    
    if not valid:
        return {"message": "No valid results yet", "valid_pairs": 0}
    
    def avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else 0

    def safe_get(result, key1, key2, default=0):
        try:
            return result.get(key1, {}).get(key2, default) or default
        except:
            return default

    summary = {
        "total_pairs": len(BIOGRAPHY_PAIRS),
        "valid_pairs": len(valid),
        "skipped_pairs": len(all_results) - len(valid),
        "wikipedia_metrics": {
            "avg_word_count_women": avg([safe_get(r, "wiki_woman", "word_count") for r in valid]),
            "avg_word_count_men": avg([safe_get(r, "wiki_man", "word_count") for r in valid]),
            "avg_references_women": avg([safe_get(r, "wiki_woman", "num_references") for r in valid]),
            "avg_references_men": avg([safe_get(r, "wiki_man", "num_references") for r in valid]),
            "avg_links_women": avg([safe_get(r, "wiki_woman", "num_internal_links") for r in valid]),
            "avg_links_men": avg([safe_get(r, "wiki_man", "num_internal_links") for r in valid]),
            "avg_categories_women": avg([safe_get(r, "wiki_woman", "num_categories") for r in valid]),
            "avg_categories_men": avg([safe_get(r, "wiki_man", "num_categories") for r in valid]),
        },
        "nlp_metrics": {
            "avg_domesticity_women": avg([safe_get(r, "nlp_woman", "domesticity_index") for r in valid if r.get("nlp_woman")]),
            "avg_domesticity_men": avg([safe_get(r, "nlp_man", "domesticity_index") for r in valid if r.get("nlp_man")]),
            "avg_epistemic_density_women": avg([safe_get(r, "nlp_woman", "epistemic_density") for r in valid if r.get("nlp_woman")]),
            "avg_epistemic_density_men": avg([safe_get(r, "nlp_man", "epistemic_density") for r in valid if r.get("nlp_man")]),
            "avg_agency_ratio_women": avg([safe_get(r, "nlp_woman", "agency_ratio") for r in valid if r.get("nlp_woman")]),
            "avg_agency_ratio_men": avg([safe_get(r, "nlp_man", "agency_ratio") for r in valid if r.get("nlp_man")]),
        },
        "llm_audit": {
            "avg_bias_score_women": avg([r["llm_audit"]["bias_score_woman"] for r in valid if r.get("llm_audit") and not r["llm_audit"].get("error")]),
            "avg_bias_score_men": avg([r["llm_audit"]["bias_score_man"] for r in valid if r.get("llm_audit") and not r["llm_audit"].get("error")]),
        }
    }
    return summary


@app.delete("/results")
def clear_results():
    """Clear all results and reset status."""
    if os.path.exists(RESULTS_FILE):
        os.remove(RESULTS_FILE)
    save_status({"status": "idle", "progress": 0})
    return {"message": "Results cleared"}
