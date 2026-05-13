"""
Wikipedia Extractor v7
- Uses wikipedia-api (wikipediaapi)
- Improved page disambiguation with wiki_hint, area keywords and direct_wiki_url
- Counts references from rendered Wikipedia HTML using cite_note markers
- Counts num_edits as the real number of page revisions via MediaWiki pagination
- Caches results to avoid redundant API calls
"""

import os
import json
import re
import time
import logging
from typing import Optional, List, Dict, Tuple
from urllib.parse import unquote

import httpx
import wikipediaapi
import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ─────────────────────────────────────────────────────────────────────────────
# Logging and app
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_VERSION = "7.0.0"
USER_AGENT = "GenderBiasAnalyzer/7.0 (research; University of Deusto)"
MW_URL = "https://es.wikipedia.org/w/api.php"

app = FastAPI(title="Wikipedia Extractor v7", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Cache and configuration
# ─────────────────────────────────────────────────────────────────────────────

CACHE_DIR = "/app/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
_LEXICON_PATH = os.path.join(CONFIG_DIR, "lexicons", "scientific.yaml")

with open(_LEXICON_PATH, encoding="utf-8") as _f:
    SCIENCE_KEYWORDS: List[str] = yaml.safe_load(_f)["scientific_keywords"]


wiki = wikipediaapi.Wikipedia(
    language="es",
    user_agent=USER_AGENT,
)


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class ExtractionRequest(BaseModel):
    nombre: str
    genero: str
    wiki_hint: Optional[str] = None
    area: Optional[str] = None
    direct_wiki_url: Optional[str] = None


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
    num_edits: int = 0

    # Page length is not the same as number of edits.
    page_length: int = 0

    image_names: List[str] = []
    creation_date: Optional[str] = None

    raw_text: Optional[str] = None
    summary: Optional[str] = None
    categories: List[str] = []
    links: List[str] = []

    error: Optional[str] = None
    disambiguation_note: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def cache_key(
    nombre: str,
    wiki_hint: Optional[str] = None,
    direct_wiki_url: Optional[str] = None,
) -> str:
    """
    Cache key includes nombre plus optional hint/url so that the same person name
    can be cached differently if disambiguation inputs change.
    """
    raw = "|".join([
        nombre or "",
        wiki_hint or "",
        direct_wiki_url or "",
    ])
    safe = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE).strip()
    safe = re.sub(r"\s+", "_", safe)
    return safe[:180] or "unknown"


def cache_path(
    nombre: str,
    wiki_hint: Optional[str] = None,
    direct_wiki_url: Optional[str] = None,
) -> str:
    return os.path.join(CACHE_DIR, f"{cache_key(nombre, wiki_hint, direct_wiki_url)}.json")


def from_cache(
    nombre: str,
    wiki_hint: Optional[str] = None,
    direct_wiki_url: Optional[str] = None,
) -> Optional[Dict]:
    p = cache_path(nombre, wiki_hint, direct_wiki_url)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def to_cache(
    nombre: str,
    data: Dict,
    wiki_hint: Optional[str] = None,
    direct_wiki_url: Optional[str] = None,
) -> None:
    p = cache_path(nombre, wiki_hint, direct_wiki_url)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Image filtering
# ─────────────────────────────────────────────────────────────────────────────

_IMG_EXCLUDE = re.compile(
    r"(?i)("
    r"flag_of|bandera_de|"
    r"\bicon\b|_icon\.|icon_|"
    r"\blogo\b|_logo\.|logo_|"
    r"commons-logo|wikimedia.logo|"
    r"disambig|"
    r"\bstub\b|"
    r"question.mark|"
    r"edit.icon|pencil.icon|"
    r"padlock|lock.icon|"
    r"symbol_support|symbol_oppose|symbol_neutral|"
    r"wikiquotebar|wikisource|wiktionary|"
    r"postscript.svg|"
    r"\.svg$"
    r")",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Reference counting
# ─────────────────────────────────────────────────────────────────────────────

def _count_refs_from_rendered_html(html: str) -> int:
    """
    Count rendered references from Wikipedia HTML.

    This is the preferred method because it matches what Wikipedia displays in
    the final 'Referencias' section after templates, reused references and named
    references have been expanded by MediaWiki.

    Spanish Wikipedia references commonly appear as:
      - <li id="cite_note-...">
      - <li about="#cite_note-...">
      - items inside <ol class="references">
    """
    if not html:
        return 0

    cite_notes = set()

    # Count id="cite_note-..." and about="#cite_note-..."
    for attr_value in re.findall(
        r'\b(?:id|about)\s*=\s*["\'](#?cite_note[-_][^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        normalized = attr_value.lstrip("#").strip()
        cite_notes.add(normalized)

    if cite_notes:
        return len(cite_notes)

    # Fallback: count <li> elements inside <ol class="references"> blocks
    reference_blocks = re.findall(
        r'<ol\b[^>]*class\s*=\s*["\'][^"\']*\breferences\b[^"\']*["\'][^>]*>(.*?)</ol>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    total = 0
    for block in reference_blocks:
        total += len(re.findall(r"<li\b", block, flags=re.IGNORECASE))

    return total


def _count_refs_from_wikitext(wikitext: str) -> int:
    """
    Fallback reference counter from raw wikitext.

    This is less reliable than rendered HTML because MediaWiki templates and
    reused references may not correspond one-to-one with the final numbered
    bibliography.
    """
    if not wikitext:
        return 0

    # Remove explicit references blocks to avoid double-counting declarations.
    wikitext_clean = re.sub(
        r"<references\b[^>]*/>",
        "",
        wikitext,
        flags=re.IGNORECASE,
    )
    wikitext_clean = re.sub(
        r"<references\b[^>]*>.*?</references\s*>",
        "",
        wikitext_clean,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Named references with content.
    named_refs = set()

    for match in re.findall(
        r"<ref\b[^>]*\bname\s*=\s*['\"]?([^'\"/> \t\r\n]+)['\"]?[^>/]*>",
        wikitext_clean,
        flags=re.IGNORECASE,
    ):
        named_refs.add(match.strip())

    # Anonymous non-self-closing references.
    anonymous_refs = re.findall(
        r"<ref(?![^>]*\bname\s*=)(?![^>]*/>)[^>]*>",
        wikitext_clean,
        flags=re.IGNORECASE,
    )

    return len(named_refs) + len(anonymous_refs)


def fetch_rendered_html(title: str) -> str:
    """
    Fetch rendered article HTML through action=parse.
    """
    r = httpx.get(
        MW_URL,
        params={
            "action": "parse",
            "page": title,
            "redirects": "1",
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=45,
    )
    r.raise_for_status()
    return r.json().get("parse", {}).get("text", "") or ""


# ─────────────────────────────────────────────────────────────────────────────
# Revision counting / edit counting
# ─────────────────────────────────────────────────────────────────────────────

def fetch_revision_stats(title: str) -> Dict:
    """
    Return real revision statistics for a Wikipedia page.

    num_edits is calculated by paginating over all revisions with rvlimit=max.
    This is slower than reading page metadata, but it returns the real number
    of revisions/edits visible through the MediaWiki revisions API.

    Returns:
      {
        "num_edits": int,
        "creation_date": Optional[str],
        "latest_revision_timestamp": Optional[str]
      }
    """
    num_edits = 0
    creation_date = None
    latest_revision_timestamp = None

    params = {
        "action": "query",
        "titles": title,
        "redirects": "1",
        "prop": "revisions",
        "rvprop": "ids|timestamp",
        "rvlimit": "max",
        "rvdir": "newer",
        "format": "json",
        "formatversion": "2",
    }

    try:
        while True:
            r = httpx.get(
                MW_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=45,
            )
            r.raise_for_status()
            data = r.json()

            pages = data.get("query", {}).get("pages", [])
            if not pages:
                break

            page = pages[0]
            if page.get("missing"):
                break

            revisions = page.get("revisions", []) or []
            if revisions:
                if creation_date is None:
                    creation_date = revisions[0].get("timestamp", "")[:10] or None

                latest_revision_timestamp = revisions[-1].get("timestamp")

            num_edits += len(revisions)

            cont = data.get("continue")
            if not cont or "rvcontinue" not in cont:
                break

            params.update(cont)

            # Be polite with the API during large pages.
            time.sleep(0.05)

    except Exception as e:
        logger.warning(f"Could not fetch revision stats for '{title}': {e}")

    return {
        "num_edits": num_edits,
        "creation_date": creation_date,
        "latest_revision_timestamp": latest_revision_timestamp,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Metadata fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_page_metadata(title: str) -> Dict:
    """
    Fetch article metadata:
      - page_length from prop=info
      - num_references from rendered HTML cite_note markers
      - num_images from pageimages + images
      - num_edits from full revision pagination
      - creation_date from first revision timestamp
    """
    result = {
        "creation_date": None,
        "page_length": 0,
        "num_references": 0,
        "num_images": 0,
        "image_names": [],
        "num_edits": 0,
    }

    try:
        r = httpx.get(
            MW_URL,
            params={
                "action": "query",
                "titles": title,
                "redirects": "1",
                "prop": "revisions|info|images|pageimages",
                "rvprop": "content|timestamp",
                "rvslots": "main",
                "rvlimit": "1",
                "rvdir": "older",
                "inprop": "url",
                "imlimit": "50",
                "piprop": "name",
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=45,
        )
        r.raise_for_status()

        data = r.json()
        pages = data.get("query", {}).get("pages", [])
        page = pages[0] if pages else {}

        if page.get("missing"):
            logger.warning(f"fetch_page_metadata: page missing for '{title}'")
            return result

        resolved_title = page.get("title", title)
        result["page_length"] = page.get("length", 0)

        # References: primary method from rendered HTML.
        try:
            rendered_html = fetch_rendered_html(resolved_title)
            result["num_references"] = _count_refs_from_rendered_html(rendered_html)

            logger.info(
                f"References for '{resolved_title}' from rendered HTML: "
                f"{result['num_references']}"
            )

        except Exception as e:
            logger.warning(
                f"Rendered HTML reference count failed for '{resolved_title}': {e}; "
                f"falling back to wikitext"
            )

            wikitext = ""
            revisions = page.get("revisions", []) or []
            if revisions:
                rev = revisions[0]

                slots = rev.get("slots", {})
                if slots:
                    main_slot = slots.get("main", {})
                    wikitext = (
                        main_slot.get("content", "")
                        or main_slot.get("*", "")
                    )

                if not wikitext:
                    wikitext = rev.get("content", "") or rev.get("*", "")

            result["num_references"] = _count_refs_from_wikitext(wikitext)

        # Images.
        lead_image = page.get("pageimage", "")

        raw_images = [
            img.get("title", "").replace("File:", "").replace("Archivo:", "")
            for img in page.get("images", []) or []
        ]

        person_images = [
            img for img in raw_images
            if img and not _IMG_EXCLUDE.search(img)
        ]

        if lead_image and lead_image not in person_images:
            person_images = [lead_image] + person_images

        result["image_names"] = person_images
        result["num_images"] = len(person_images)

        # Real edit count and creation date.
        revision_stats = fetch_revision_stats(resolved_title)
        result["num_edits"] = revision_stats["num_edits"]
        result["creation_date"] = revision_stats["creation_date"]

        logger.info(
            f"fetch_page_metadata '{resolved_title}': "
            f"refs={result['num_references']}, "
            f"edits={result['num_edits']}, "
            f"creation_date={result['creation_date']}, "
            f"images={result['num_images']}, "
            f"page_length={result['page_length']}"
        )

    except Exception as e:
        logger.warning(f"fetch_page_metadata failed for '{title}': {e}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible metadata helper
# ─────────────────────────────────────────────────────────────────────────────

def get_metadata(title: str) -> Dict:
    """
    Backward-compatible helper.

    Prefer fetch_page_metadata() in the main extraction path.
    """
    try:
        r = httpx.get(
            MW_URL,
            params={
                "action": "query",
                "prop": "info",
                "titles": title,
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        r.raise_for_status()

        pages = r.json().get("query", {}).get("pages", [])
        page = pages[0] if pages else {}

        revision_stats = fetch_revision_stats(page.get("title", title))

        return {
            "creation_date": revision_stats["creation_date"],
            "page_length": page.get("length", 0),
            "num_edits": revision_stats["num_edits"],
        }

    except Exception as e:
        logger.warning(f"Could not get metadata for '{title}': {e}")
        return {
            "creation_date": None,
            "page_length": 0,
            "num_edits": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scientist page disambiguation
# ─────────────────────────────────────────────────────────────────────────────

def is_scientist_page(pagina, area: Optional[str] = None) -> bool:
    """
    Heuristic: decide whether a Wikipedia page describes a scientist,
    researcher, academic, engineer or science-related professional.
    """
    text_lower = (pagina.summary or "").lower()
    cats_lower = " ".join(pagina.categories.keys()).lower() if pagina.categories else ""
    combined = text_lower + " " + cats_lower

    if area:
        area_kws = re.split(r"[/,;|]", area.lower())
        for kw in area_kws:
            kw = kw.strip()
            if len(kw) > 3 and kw in combined:
                return True

    for kw in SCIENCE_KEYWORDS:
        if kw.lower() in combined:
            return True

    return False


def _title_from_direct_wiki_url(direct_wiki_url: str) -> Optional[str]:
    """
    Extract Spanish Wikipedia title from a /wiki/... URL.
    """
    if not direct_wiki_url:
        return None

    try:
        if "/wiki/" not in direct_wiki_url:
            return None

        path_title = direct_wiki_url.rstrip("/").split("/wiki/")[-1]
        title = unquote(path_title).replace("_", " ").strip()
        return title or None

    except Exception:
        return None


def find_scientist_page(
    nombre: str,
    wiki_hint: Optional[str],
    area: Optional[str],
    direct_wiki_url: Optional[str] = None,
):
    """
    Attempt to find the correct Spanish Wikipedia page.

    Strategy:
      0. direct_wiki_url override
      1. wiki_hint exact title
      2. nombre as-is
      3. MediaWiki search and science-page heuristic
    """
    if direct_wiki_url:
        title = _title_from_direct_wiki_url(direct_wiki_url)
        if title:
            pagina = wiki.page(title)
            if pagina.exists():
                logger.info(f"direct_wiki_url resolved '{nombre}' → '{title}'")
                return pagina, f"Found via direct_wiki_url: '{title}'"

            logger.warning(
                f"direct_wiki_url page not found for '{nombre}': '{title}' — "
                f"falling through to normal lookup"
            )

    candidates = []

    if wiki_hint and wiki_hint != nombre:
        candidates.append(wiki_hint)

    candidates.append(nombre)

    for candidate in candidates:
        pagina = wiki.page(candidate)

        if not pagina.exists():
            continue

        cats = list(pagina.categories.keys()) if pagina.categories else []
        is_disambig = any("desambiguación" in c.lower() for c in cats)

        if not is_disambig:
            return pagina, f"Found via: '{candidate}'"

    # Fallback: MediaWiki search.
    try:
        r = httpx.get(
            MW_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": nombre,
                "srlimit": 8,
                "srnamespace": 0,
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        r.raise_for_status()

        results = r.json().get("query", {}).get("search", [])

        for item in results:
            title = item.get("title", "")
            if not title:
                continue

            p = wiki.page(title)

            if p.exists() and is_scientist_page(p, area):
                return p, f"Found via search: '{title}'"

    except Exception as e:
        logger.warning(f"Search failed for '{nombre}': {e}")

    return None, f"No Wikipedia ES page found for '{nombre}'"


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract(
    nombre: str,
    genero: str,
    wiki_hint: Optional[str] = None,
    area: Optional[str] = None,
    direct_wiki_url: Optional[str] = None,
) -> WikipediaMetrics:

    cached = from_cache(nombre, wiki_hint, direct_wiki_url)
    if cached:
        logger.info(f"Cache hit: {nombre}")
        return WikipediaMetrics(**cached)

    logger.info(
        f"Fetching Wikipedia ES: {nombre} "
        f"(hint={wiki_hint}, area={area}, direct_url={direct_wiki_url})"
    )

    result = WikipediaMetrics(nombre=nombre, genero=genero)

    try:
        pagina, note = find_scientist_page(
            nombre=nombre,
            wiki_hint=wiki_hint,
            area=area,
            direct_wiki_url=direct_wiki_url,
        )

        result.disambiguation_note = note

        if pagina is None:
            result.exists_in_wikipedia = False
            result.error = note
            to_cache(nombre, result.model_dump(), wiki_hint, direct_wiki_url)
            return result

        result.exists_in_wikipedia = True
        result.wikipedia_url = pagina.fullurl
        result.wikipedia_title = pagina.title

        texto_plano = pagina.text or ""
        enlaces = list(pagina.links.keys()) if pagina.links else []

        result.raw_text = texto_plano
        result.word_count = len(texto_plano.split())

        result.links = enlaces[:300]
        result.num_internal_links = len(enlaces)

        result.summary = (pagina.summary or "")[:600]

        cats = list(pagina.categories.keys()) if pagina.categories else []
        result.categories = cats[:80]
        result.num_categories = len(cats)

        meta = fetch_page_metadata(pagina.title)

        result.creation_date = meta["creation_date"]
        result.page_length = meta["page_length"]
        result.num_references = meta["num_references"]
        result.num_images = meta["num_images"]
        result.image_names = meta["image_names"]

        # Correct logic: real number of revisions/edits, not page length.
        result.num_edits = meta["num_edits"]

        logger.info(
            f"OK {nombre}: "
            f"{result.word_count} words, "
            f"{result.num_references} refs, "
            f"{result.num_internal_links} links, "
            f"{result.num_images} images, "
            f"{result.num_edits} edits"
        )

        to_cache(nombre, result.model_dump(), wiki_hint, direct_wiki_url)

    except Exception as e:
        result.error = str(e)[:300]
        logger.error(f"Error extracting '{nombre}': {e}", exc_info=True)
        to_cache(nombre, result.model_dump(), wiki_hint, direct_wiki_url)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# API endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "wikipedia-extractor",
        "version": APP_VERSION,
    }


@app.post("/extract", response_model=WikipediaMetrics)
def extract_one(req: ExtractionRequest):
    return extract(
        nombre=req.nombre,
        genero=req.genero,
        wiki_hint=req.wiki_hint,
        area=req.area,
        direct_wiki_url=req.direct_wiki_url,
    )


@app.post("/extract/batch")
def extract_batch(reqs: List[ExtractionRequest]):
    return {
        "results": [
            extract(
                nombre=r.nombre,
                genero=r.genero,
                wiki_hint=r.wiki_hint,
                area=r.area,
                direct_wiki_url=r.direct_wiki_url,
            ).model_dump()
            for r in reqs
        ]
    }


@app.delete("/cache")
def clear_cache():
    removed = 0

    for f in os.listdir(CACHE_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(CACHE_DIR, f))
            removed += 1

    return {"message": f"Cache cleared ({removed} entries)"}


@app.get("/cache/list")
def list_cache():
    files = [
        f.replace(".json", "").replace("_", " ")
        for f in os.listdir(CACHE_DIR)
        if f.endswith(".json")
    ]

    return {
        "entries": files,
        "count": len(files),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Optional local smoke tests
# ─────────────────────────────────────────────────────────────────────────────

def _smoke_test_reference_counts():
    """
    Run manually inside the container if needed.

    Expected examples:
      Francisco Herrera Triguero -> 4 references
      Nuria Oliver -> around 92 references, depending on current Wikipedia state
    """
    examples = [
        "Francisco Herrera Triguero",
        "Nuria Oliver",
    ]

    for title in examples:
        meta = fetch_page_metadata(title)
        print(
            title,
            {
                "num_references": meta["num_references"],
                "num_edits": meta["num_edits"],
                "creation_date": meta["creation_date"],
                "page_length": meta["page_length"],
            },
        )