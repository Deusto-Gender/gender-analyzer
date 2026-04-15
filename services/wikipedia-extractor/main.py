"""
Wikipedia Extractor Microservice
Extracts text, metadata and quantitative metrics from Spanish Wikipedia articles.
"""
import os
import json
import re
import time
import logging
from typing import Optional, List, Dict
from datetime import datetime

import httpx
import wikipedia
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Wikipedia Extractor Service",
    description="Extracts and caches Wikipedia biography data",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CACHE_DIR = "/app/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

wikipedia.set_lang("es")


class ExtractionRequest(BaseModel):
    nombre: str
    genero: str


class WikipediaMetrics(BaseModel):
    nombre: str
    genero: str
    wikipedia_url: Optional[str] = None
    exists_in_wikipedia: bool = False
    word_count: int = 0
    num_references: int = 0
    num_internal_links: int = 0
    num_categories: int = 0
    num_images: int = 0
    creation_date: Optional[str] = None
    num_edits: int = 0
    raw_text: Optional[str] = None
    summary: Optional[str] = None
    categories: List[str] = []
    links: List[str] = []
    error: Optional[str] = None


def get_cache_path(nombre: str) -> str:
    safe_name = re.sub(r'[^\w\s-]', '', nombre).strip().replace(' ', '_')
    return os.path.join(CACHE_DIR, f"{safe_name}.json")


def load_from_cache(nombre: str) -> Optional[Dict]:
    path = get_cache_path(nombre)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_to_cache(nombre: str, data: Dict):
    path = get_cache_path(nombre)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_wiki_metadata(page) -> Dict:
    """Get edit count and creation date via Wikipedia API."""
    try:
        api_url = "https://es.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "titles": page.title,
            "prop": "revisions|info",
            "rvlimit": "1",
            "rvdir": "newer",
            "rvprop": "timestamp",
            "inprop": "protection",
            "format": "json"
        }
        resp = httpx.get(api_url, params=params, timeout=10)
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        page_data = list(pages.values())[0] if pages else {}
        
        creation_date = None
        if "revisions" in page_data and page_data["revisions"]:
            creation_date = page_data["revisions"][0].get("timestamp", "")[:10]
        
        # Get total edit count
        params2 = {
            "action": "query",
            "titles": page.title,
            "prop": "info",
            "inprop": "watchers",
            "format": "json"
        }
        resp2 = httpx.get(api_url, params=params2, timeout=10)
        d2 = resp2.json()
        p2 = list(d2.get("query", {}).get("pages", {}).values())[0] if d2.get("query", {}).get("pages") else {}
        num_edits = p2.get("length", 0)
        
        return {"creation_date": creation_date, "num_edits": num_edits}
    except Exception as e:
        logger.warning(f"Could not fetch metadata: {e}")
        return {"creation_date": None, "num_edits": 0}


def count_references_in_html(page) -> int:
    """Count references from the page HTML."""
    try:
        html = page.html()
        refs = re.findall(r'<li[^>]*id="cite_note', html)
        if not refs:
            refs = re.findall(r'class="reference"', html)
        return len(refs)
    except:
        return 0


def count_images_in_page(page) -> int:
    try:
        return len([img for img in page.images if not img.endswith('.svg') or 'logo' not in img.lower()])
    except:
        return 0


def extract_wikipedia_data(nombre: str, genero: str) -> WikipediaMetrics:
    cached = load_from_cache(nombre)
    if cached:
        logger.info(f"Cache hit for {nombre}")
        return WikipediaMetrics(**cached)

    logger.info(f"Fetching Wikipedia data for: {nombre}")
    result = WikipediaMetrics(nombre=nombre, genero=genero)

    try:
        time.sleep(0.5)  # Rate limiting
        search_results = wikipedia.search(nombre, results=5)
        
        page = None
        for candidate in search_results:
            try:
                p = wikipedia.page(candidate, auto_suggest=False)
                # Verify it's about the right person
                title_match = any(
                    part.lower() in p.title.lower() 
                    for part in nombre.split()[:2]
                )
                if title_match:
                    page = p
                    break
            except (wikipedia.exceptions.DisambiguationError, wikipedia.exceptions.PageError):
                continue

        if page is None:
            result.exists_in_wikipedia = False
            result.error = "No se encontró página en Wikipedia"
            save_to_cache(nombre, result.model_dump())
            return result

        result.exists_in_wikipedia = True
        result.wikipedia_url = page.url

        # Quantitative metrics
        content = page.content
        result.raw_text = content
        result.word_count = len(content.split())
        result.summary = page.summary[:500] if page.summary else ""
        result.num_internal_links = len(page.links) if page.links else 0
        result.links = list(page.links[:100]) if page.links else []
        result.categories = list(page.categories[:50]) if page.categories else []
        result.num_categories = len(result.categories)
        result.num_images = count_images_in_page(page)
        result.num_references = count_references_in_html(page)

        # Metadata from API
        meta = extract_wiki_metadata(page)
        result.creation_date = meta["creation_date"]
        result.num_edits = meta["num_edits"]

        save_to_cache(nombre, result.model_dump())
        logger.info(f"Successfully extracted data for {nombre}: {result.word_count} words")

    except wikipedia.exceptions.DisambiguationError as e:
        result.exists_in_wikipedia = False
        result.error = f"Página ambigua: {str(e)[:100]}"
        save_to_cache(nombre, result.model_dump())
    except wikipedia.exceptions.PageError:
        result.exists_in_wikipedia = False
        result.error = "Página no encontrada"
        save_to_cache(nombre, result.model_dump())
    except Exception as e:
        result.error = f"Error: {str(e)[:200]}"
        logger.error(f"Error extracting {nombre}: {e}")
        save_to_cache(nombre, result.model_dump())

    return result


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "wikipedia-extractor"}


@app.post("/extract", response_model=WikipediaMetrics)
def extract_biography(request: ExtractionRequest):
    """Extract Wikipedia metrics for a single biography."""
    return extract_wikipedia_data(request.nombre, request.genero)


@app.post("/extract/batch")
def extract_batch(requests: List[ExtractionRequest]):
    """Extract Wikipedia metrics for multiple biographies."""
    results = []
    for req in requests:
        result = extract_wikipedia_data(req.nombre, req.genero)
        results.append(result.model_dump())
    return {"results": results}


@app.get("/extract/{nombre}")
def get_cached(nombre: str):
    """Get cached result for a biography."""
    cached = load_from_cache(nombre)
    if not cached:
        raise HTTPException(status_code=404, detail="No cached data found")
    return cached


@app.delete("/cache/{nombre}")
def clear_cache(nombre: str):
    """Clear cache for a specific biography."""
    path = get_cache_path(nombre)
    if os.path.exists(path):
        os.remove(path)
        return {"message": f"Cache cleared for {nombre}"}
    raise HTTPException(status_code=404, detail="No cache entry found")


@app.get("/cache/list")
def list_cache():
    """List all cached entries."""
    files = [f.replace('.json', '').replace('_', ' ') for f in os.listdir(CACHE_DIR) if f.endswith('.json')]
    return {"cached_entries": files, "count": len(files)}
