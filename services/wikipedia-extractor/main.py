"""
Wikipedia Extractor v6
- Uses wikipedia-api (wikipediaapi) as in the notebook
- Improved page disambiguation: uses wiki_hint and area keywords to select
  the correct scientist page when multiple pages share a name
- Counts references properly via wikitext <ref> parsing
- Caches all results to avoid redundant API calls
"""
import os, json, re, time, logging
from typing import Optional, List, Dict
import httpx
import wikipediaapi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Wikipedia Extractor v6", version="6.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CACHE_DIR = "/app/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

wiki = wikipediaapi.Wikipedia(
    language="es",
    user_agent="GenderBiasAnalyzer/6.0 (research; University of Deusto)"
)

# Science-related keywords used for disambiguation
SCIENCE_KEYWORDS = [
    "investigador", "investigadora", "científico", "científica", "doctor", "doctora",
    "profesor", "profesora", "catedrático", "catedrática", "ingeniero", "ingeniera",
    "biól", "físic", "químic", "matemátic", "informátic", "astrónom",
    "biólog", "neurocientíf", "robót", "inteligencia artificial", "universidad",
    "instituto", "csic", "laboratorio", "premio", "investigación", "tecnología",
    "computación", "algoritmo", "robótica", "nanociencia", "astrofísica",
    "bioinformática", "neurociencia", "oncología", "bioquímica"
]


class ExtractionRequest(BaseModel):
    nombre: str
    genero: str
    wiki_hint: Optional[str] = None   # exact Wikipedia page title to try first
    area: Optional[str] = None        # scientific area for disambiguation


class WikipediaMetrics(BaseModel):
    nombre: str
    genero: str
    wikipedia_url: Optional[str] = None
    wikipedia_title: Optional[str] = None
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
    disambiguation_note: Optional[str] = None


def cache_path(nombre: str) -> str:
    safe = re.sub(r'[^\w\s-]', '', nombre).strip().replace(' ', '_')
    return os.path.join(CACHE_DIR, f"{safe}.json")


def from_cache(nombre: str) -> Optional[Dict]:
    p = cache_path(nombre)
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def to_cache(nombre: str, data: Dict):
    with open(cache_path(nombre), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def count_references(title: str) -> int:
    """
    Count the number of footnote references in a Wikipedia ES article.

    Wikipedia references appear as numbered footnotes [1], [2], ... [N]
    in the body text, and are listed in a "Referencias" section at the end.
    The total count equals the highest cite_note-N anchor in the HTML,
    which matches exactly what the reader sees (e.g., 63 for Mateo Valero).

    Strategy (3 methods, returns the first successful one):
      1. Rendered HTML  → count unique id="cite_note-N" anchors (most reliable)
      2. Wikitext       → count unique named/unnamed <ref> groups
      3. prop=references API → direct list (often empty, kept as last resort)
    """
    url = "https://es.wikipedia.org/w/api.php"
    headers = {"User-Agent": "GenderBiasAnalyzer/6.0 (research)"}

    # ── Method 1: Rendered HTML — count unique cite_note-N anchor IDs ─────────
    # The rendered page has <li id="cite_note-1">, <li id="cite_note-2">, ...
    # The maximum N equals the total number of numbered references.
    try:
        r = httpx.get(url, params={
            "action": "parse", "page": title,
            "prop": "text", "format": "json",
            "disablelimitreport": "1"
        }, headers=headers, timeout=30)
        html = r.json().get("parse", {}).get("text", {}).get("*", "")
        if html:
            # Find all cite_note-N anchors (N is always a pure integer for numbered refs)
            cite_ids = re.findall(r'id="cite_note-(\d+)"', html)
            if cite_ids:
                count = max(int(n) for n in cite_ids)
                logger.info(f"References for '{title}': {count} (HTML cite_note method)")
                return count
            # Fallback within Method 1: count any cite_note anchor
            all_cite = re.findall(r'id="cite_note-[^"]*"', html)
            if all_cite:
                logger.info(f"References for '{title}': {len(all_cite)} (HTML all cite_note)")
                return len(all_cite)
    except Exception as e:
        logger.warning(f"Method 1 (HTML) failed for '{title}': {e}")

    # ── Method 2: Wikitext — count unique <ref> entries ───────────────────────
    # Each <ref name="X"> group counts once; anonymous <ref> each count once.
    try:
        r2 = httpx.get(url, params={
            "action": "parse", "page": title,
            "prop": "wikitext", "format": "json"
        }, headers=headers, timeout=25)
        wikitext = r2.json().get("parse", {}).get("wikitext", {}).get("*", "")
        if wikitext:
            # Named refs: <ref name="X">...</ref> — count unique names
            named = set(re.findall(r'<ref\s+name=["\']([^"\']+)["\']', wikitext, re.IGNORECASE))
            # Self-closing named refs: <ref name="X"/> (reuses existing, don't double-count)
            # Anonymous refs: <ref> without a name attribute
            anon = re.findall(r'<ref(?!\s+name)(?:\s[^>]*)?>(?!</ref>)', wikitext, re.IGNORECASE)
            count = len(named) + len(anon)
            if count > 0:
                logger.info(f"References for '{title}': {count} (wikitext method, {len(named)} named + {len(anon)} anon)")
                return count
    except Exception as e:
        logger.warning(f"Method 2 (wikitext) failed for '{title}': {e}")

    # ── Method 3: prop=references ─────────────────────────────────────────────
    try:
        r3 = httpx.get(url, params={
            "action": "parse", "page": title,
            "prop": "references", "format": "json"
        }, headers=headers, timeout=20)
        refs = r3.json().get("parse", {}).get("references", [])
        if refs:
            logger.info(f"References for '{title}': {len(refs)} (prop=references method)")
            return len(refs)
    except Exception as e:
        logger.warning(f"Method 3 (prop=references) failed for '{title}': {e}")

    logger.warning(f"All reference-counting methods failed for '{title}', returning 0")
    return 0


def get_creation_date(title: str) -> Optional[str]:
    """Get article creation date via MediaWiki API (oldest revision)."""
    try:
        r = httpx.get("https://es.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "revisions", "titles": title,
            "rvprop": "timestamp", "rvlimit": 1, "rvdir": "newer", "format": "json"
        }, headers={"User-Agent": "GenderBiasAnalyzer/6.0"}, timeout=20)
        pages = r.json().get("query", {}).get("pages", {})
        page = list(pages.values())[0] if pages else {}
        if "revisions" in page:
            return page["revisions"][0].get("timestamp", "")[:10]
    except Exception as e:
        logger.warning(f"Could not get creation date for {title}: {e}")
    return None


def get_edit_count(title: str) -> int:
    """Get total number of revisions (edit count)."""
    try:
        r = httpx.get("https://es.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "info", "titles": title,
            "format": "json"
        }, timeout=15)
        pages = r.json().get("query", {}).get("pages", {})
        page = list(pages.values())[0] if pages else {}
        return page.get("length", 0)
    except:
        return 0


def is_scientist_page(pagina, area: Optional[str] = None) -> bool:
    """
    Heuristic: does this Wikipedia page describe a scientist/researcher?
    Used when multiple pages exist for the same name (disambiguation).
    """
    text_lower = (pagina.summary or "").lower()
    cats_lower = " ".join(pagina.categories.keys()).lower() if pagina.categories else ""
    combined = text_lower + " " + cats_lower

    # Check area keywords if provided
    if area:
        area_kws = area.lower().split("/")
        for kw in area_kws:
            kw = kw.strip()
            if len(kw) > 3 and kw in combined:
                return True

    # Check generic science keywords
    for kw in SCIENCE_KEYWORDS:
        if kw in combined:
            return True
    return False


def find_scientist_page(nombre: str, wiki_hint: Optional[str], area: Optional[str]):
    """
    Attempt to find the correct Wikipedia page for a scientist.
    Strategy:
      1. Try wiki_hint (exact title from pairs.json) first
      2. Try the nombre as-is
      3. Try MediaWiki search and pick first result that looks scientific
    Returns (page, note) or (None, error_msg)
    """
    candidates = []
    if wiki_hint and wiki_hint != nombre:
        candidates.append(wiki_hint)
    candidates.append(nombre)

    for candidate in candidates:
        pagina = wiki.page(candidate)
        if pagina.exists():
            # Check if it's a disambiguation page
            cats = list(pagina.categories.keys()) if pagina.categories else []
            is_disambig = any("desambiguación" in c.lower() for c in cats)
            if not is_disambig:
                note = f"Found via: '{candidate}'"
                return pagina, note

    # Fallback: MediaWiki search
    try:
        r = httpx.get("https://es.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search",
            "srsearch": nombre, "srlimit": 8,
            "srnamespace": 0, "format": "json"
        }, timeout=15)
        results = r.json().get("query", {}).get("search", [])
        for result in results:
            title = result.get("title", "")
            p = wiki.page(title)
            if p.exists() and is_scientist_page(p, area):
                return p, f"Found via search: '{title}'"
    except Exception as e:
        logger.warning(f"Search failed for {nombre}: {e}")

    return None, f"No Wikipedia ES page found for '{nombre}'"


def extract(nombre: str, genero: str,
            wiki_hint: Optional[str] = None,
            area: Optional[str] = None) -> WikipediaMetrics:

    cached = from_cache(nombre)
    if cached:
        logger.info(f"Cache hit: {nombre}")
        return WikipediaMetrics(**cached)

    logger.info(f"Fetching Wikipedia ES: {nombre} (hint={wiki_hint})")
    result = WikipediaMetrics(nombre=nombre, genero=genero)

    try:
        time.sleep(0.5)

        pagina, note = find_scientist_page(nombre, wiki_hint, area)
        result.disambiguation_note = note

        if pagina is None:
            result.exists_in_wikipedia = False
            result.error = note
            to_cache(nombre, result.model_dump())
            return result

        result.exists_in_wikipedia = True
        result.wikipedia_url = pagina.fullurl
        result.wikipedia_title = pagina.title

        # Text metrics (same as notebook)
        texto_plano = pagina.text
        enlaces = list(pagina.links.keys())

        result.raw_text = texto_plano
        result.word_count = len(texto_plano.split())
        result.links = enlaces[:300]
        result.num_internal_links = len(enlaces)
        result.summary = (pagina.summary or "")[:600]

        cats = list(pagina.categories.keys()) if pagina.categories else []
        result.categories = cats[:80]
        result.num_categories = len(cats)

        # Metadata from MediaWiki API
        result.creation_date = get_creation_date(pagina.title)
        result.num_edits = get_edit_count(pagina.title)

        # References via multi-method HTML/wikitext parsing
        result.num_references = count_references(pagina.title)

        logger.info(f"OK {nombre}: {result.word_count} words, "
                    f"{result.num_references} refs, {result.num_internal_links} links")

        to_cache(nombre, result.model_dump())

    except Exception as e:
        result.error = str(e)[:300]
        logger.error(f"Error extracting {nombre}: {e}", exc_info=True)
        to_cache(nombre, result.model_dump())

    return result


@app.get("/health")
def health():
    return {"status": "ok", "service": "wikipedia-extractor", "version": "6.0.0"}


@app.post("/extract", response_model=WikipediaMetrics)
def extract_one(req: ExtractionRequest):
    return extract(req.nombre, req.genero, req.wiki_hint, req.area)


@app.post("/extract/batch")
def extract_batch(reqs: List[ExtractionRequest]):
    return {"results": [
        extract(r.nombre, r.genero, r.wiki_hint, r.area).model_dump()
        for r in reqs
    ]}


@app.delete("/cache")
def clear_cache():
    removed = 0
    for f in os.listdir(CACHE_DIR):
        if f.endswith('.json'):
            os.remove(os.path.join(CACHE_DIR, f))
            removed += 1
    return {"message": f"Cache cleared ({removed} entries)"}


@app.get("/cache/list")
def list_cache():
    files = [f.replace('.json', '').replace('_', ' ')
             for f in os.listdir(CACHE_DIR) if f.endswith('.json')]
    return {"entries": files, "count": len(files)}
