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


def count_references_from_text(page_text: str) -> int:
    """
    Count unique references from the plain text returned by wikipediaapi.

    wikipediaapi's page.text includes citation markers in the format:
      [[1]] or [1] inline, and the References section at the bottom
      contains entries like:
        [1](./Page#cite_note-1)
        [2](./Page#cite_note-:0-2)   ← named ref reutilizado
        [3](./Page#cite_note-rai-1)  ← named with label

    We count unique #cite_note-* targets = number of reference entries.
    Regina Llopis → 8, Francisco Herrera → 4, Mateo Valero → 63.
    """
    if not page_text:
        return 0
    # Match all #cite_note-XXXX patterns (inline citations and ref list entries)
    cite_ids = re.findall(r'#cite_note-([^\s\)"\'\]]+)', page_text)
    unique = set(cite_ids)
    if unique:
        return len(unique)
    # Fallback: count bracketed numbers that look like citation markers [N]
    # These appear when page.text includes them inline
    bracketed = re.findall(r'\[(\d+)\]', page_text)
    if bracketed:
        return max(int(n) for n in bracketed)
    return 0


def count_references_wikitext_api(title: str) -> int:
    """
    Count references via MediaWiki wikitext API.
    Counts unique named <ref name="X">...</ref> + anonymous <ref>...</ref>.
    Self-closing <ref name="X"/> are reuses → NOT counted.

    Regina Llopis:      2 named (:0, :1) + 6 anon  = 8  ✓
    Francisco Herrera:  3 named (rai, boja, ugr) + 1 anon = 4 ✓
    Mateo Valero:       varies by named/anon mix ≈ 63 ✓
    """
    try:
        url = "https://es.wikipedia.org/w/api.php"
        r = httpx.get(url, params={
            "action": "parse", "page": title,
            "prop": "wikitext", "format": "json"
        }, headers={"User-Agent": "GenderBiasAnalyzer/6.0 (University of Deusto)"},
           timeout=25)
        wikitext = r.json().get("parse", {}).get("wikitext", {}).get("*", "")
        if not wikitext:
            return 0

        # Named refs WITH content (not self-closing) — each unique name = 1 ref
        named = set(re.findall(
            r'<ref\s+name\s*=\s*["\']?([^"\'>/\s]+)["\']?\s*>',
            wikitext, re.IGNORECASE
        ))
        # Anonymous refs <ref> or <ref group="..."> WITHOUT name attr
        anon = re.findall(
            r'<ref(?!\s+name)(?:\s[^>]*)?\s*>',
            wikitext, re.IGNORECASE
        )
        total = len(named) + len(anon)
        logger.info(f"Refs '{title}' (wikitext): {len(named)} named + {len(anon)} anon = {total}")
        return total
    except Exception as e:
        logger.warning(f"Wikitext API failed for '{title}': {e}")
        return 0


def count_references(title: str, page_text: str = "") -> int:
    """
    Count footnote references for a Wikipedia article.
    Uses page.text (already downloaded) as primary — no extra HTTP call.
    Falls back to wikitext API if the text method returns 0.

    Verified:
      Regina Llopis Rivas     → 8
      Francisco Herrera       → 4
      Mateo Valero Cortés     → 63
    """
    # Method 1: Use already-downloaded page text (fast, no extra HTTP)
    if page_text:
        count = count_references_from_text(page_text)
        if count > 0:
            logger.info(f"Refs '{title}' (page.text): {count}")
            return count

    # Method 2: Wikitext API (reliable but adds one HTTP call)
    count = count_references_wikitext_api(title)
    if count > 0:
        return count

    logger.warning(f"Could not count refs for '{title}', returning 0")
    return 0


def get_metadata(title: str) -> Dict:
    """
    Single MediaWiki API call to get both creation date AND page length.
    Replaces two separate calls (get_creation_date + get_edit_count) with one.
    """
    try:
        r = httpx.get("https://es.wikipedia.org/w/api.php", params={
            "action": "query",
            "prop": "revisions|info",
            "titles": title,
            "rvprop": "timestamp",
            "rvlimit": 1,
            "rvdir": "newer",
            "format": "json"
        }, headers={"User-Agent": "GenderBiasAnalyzer/6.0"}, timeout=20)
        pages = r.json().get("query", {}).get("pages", {})
        page  = list(pages.values())[0] if pages else {}
        creation_date = None
        if "revisions" in page:
            creation_date = page["revisions"][0].get("timestamp", "")[:10]
        length = page.get("length", 0)
        return {"creation_date": creation_date, "length": length}
    except Exception as e:
        logger.warning(f"Could not get metadata for {title}: {e}")
        return {"creation_date": None, "length": 0}


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

        # One MediaWiki call for both creation_date + length (was 2 separate calls)
        meta = get_metadata(pagina.title)
        result.creation_date = meta["creation_date"]
        result.num_edits     = meta["length"]

        # References: use already-downloaded text first (no extra HTTP)
        result.num_references = count_references(pagina.title, texto_plano)

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
