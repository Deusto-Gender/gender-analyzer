"""
NLP Analyzer Microservice
Performs linguistic analysis of biography texts:
- Domesticity Index
- Epistemic Adjective Density
- Agency Ratio (Active/Passive verbs)
- Scientific Link Centrality
"""
import re
import logging
from typing import List, Dict, Optional, Tuple
from collections import Counter

import spacy
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NLP Analyzer Service",
    description="Linguistic and discourse analysis of biography texts",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Load spaCy model
try:
    nlp = spacy.load("es_core_news_lg")
    logger.info("Loaded es_core_news_lg")
except OSError:
    try:
        nlp = spacy.load("es_core_news_md")
        logger.info("Loaded es_core_news_md")
    except OSError:
        nlp = spacy.load("es_core_news_sm")
        logger.info("Loaded es_core_news_sm")

# ── Lexicons ──────────────────────────────────────────────────────────────────

DOMESTIC_KEYWORDS = [
    "madre", "esposa", "hija", "hermana", "familia", "casada", "matrimonio",
    "marido", "esposo", "pareja", "maternidad", "hijos", "crianza", "hogar",
    "casó", "divorci", "viuda", "abuela", "nuera", "suegra", "cuñada",
    "nacida", "nacida en", "infancia", "niñez", "adolescencia"
]

EPISTEMIC_ADJECTIVES = [
    "brillante", "genial", "pionera", "pionero", "experta", "experto",
    "influyente", "destacada", "destacado", "referente", "innovadora", "innovador",
    "prolífica", "prolífico", "renombrada", "renombrado", "excelente", "distinguida",
    "distinguido", "sobresaliente", "eminente", "insigne", "célebre", "reconocida",
    "reconocido", "prestigiosa", "prestigioso", "líder", "visionaria", "visionario",
    "revolucionaria", "revolucionario", "notable", "excepcional", "talentosa",
    "talentoso", "inteligente", "rigurosa", "riguroso", "meticulosa", "meticuloso",
    "creativa", "creativo", "inventora", "inventor"
]

PERSONALITY_ADJECTIVES = [
    "trabajadora", "trabajador", "amable", "constante", "dedicada", "dedicado",
    "apasionada", "apasionado", "entusiasta", "humilde", "discreta", "discreto",
    "comprometida", "comprometido", "perseverante", "tenaz", "esforzada", "esforzado",
    "valiente", "luchadora", "luchador", "emprendedora", "emprendedor", "activa",
    "activo", "dinámica", "dinámico", "optimista", "resiliente"
]

# Passive voice markers in Spanish
PASSIVE_PATTERNS = [
    r'\b(fue|fueron|es|son|era|eran|ha sido|han sido|había sido|habían sido)\s+\w+da\b',
    r'\b(fue|fueron|es|son|era|eran)\s+\w+do\b',
    r'\bse\s+(le|les)\s+(otorgó|concedió|asignó|nombró|eligió|seleccionó)\b',
    r'\bse\s+\w+(ó|aron)\b',
    r'\bfue\s+(nombrada|nombrado|elegida|elegido|seleccionada|seleccionado|galardonada|galardonado)\b',
    r'\b(recibió|recibieron)\s+(el|la|los|las)\s+\w+\s+(premio|galardón|reconocimiento)\b',
]

SCIENTIFIC_CATEGORIES = [
    "ciencia", "investigación", "tecnología", "ingeniería", "matemáticas",
    "física", "química", "biología", "informática", "computación", "robótica",
    "inteligencia artificial", "nanotecnología", "astrofísica", "biotecnología",
    "neurociencia", "software", "algoritmo", "publicación", "revista científica",
    "universidad", "instituto", "laboratorio", "tesis", "doctorado", "cátedra",
    "premio", "beca", "grant", "proyecto", "patente"
]


class NLPRequest(BaseModel):
    nombre: str
    genero: str
    text: str
    links: List[str] = []
    categories: List[str] = []


class NLPMetrics(BaseModel):
    nombre: str
    genero: str
    domesticity_index: float = 0.0
    epistemic_adjectives_count: int = 0
    personality_adjectives_count: int = 0
    epistemic_density: float = 0.0
    agency_ratio: float = 0.0
    active_verbs: int = 0
    passive_verbs: int = 0
    scientific_links_ratio: float = 0.0
    top_adjectives: List[str] = []
    top_nouns: List[str] = []
    domestic_keywords_found: List[str] = []
    text_length_tokens: int = 0
    sentences_count: int = 0
    avg_sentence_length: float = 0.0
    error: Optional[str] = None


def compute_domesticity_index(text: str) -> Tuple[float, List[str]]:
    """I_d = Σ(domestic_keywords) / N * 1000"""
    text_lower = text.lower()
    words = text_lower.split()
    N = len(words) if words else 1
    
    found = []
    count = 0
    for kw in DOMESTIC_KEYWORDS:
        occurrences = len(re.findall(r'\b' + re.escape(kw) + r'\b', text_lower))
        if occurrences > 0:
            found.append(kw)
            count += occurrences
    
    index = (count / N) * 1000
    return round(index, 4), found


def compute_epistemic_density(doc) -> Tuple[int, int, float]:
    """Count epistemic vs personality adjectives."""
    text_lower = doc.text.lower()
    
    epistemic_count = 0
    for adj in EPISTEMIC_ADJECTIVES:
        epistemic_count += len(re.findall(r'\b' + re.escape(adj) + r'\b', text_lower))
    
    personality_count = 0
    for adj in PERSONALITY_ADJECTIVES:
        personality_count += len(re.findall(r'\b' + re.escape(adj) + r'\b', text_lower))
    
    total = epistemic_count + personality_count
    density = epistemic_count / total if total > 0 else 0.0
    
    return epistemic_count, personality_count, round(density, 4)


def compute_agency_ratio(text: str, doc) -> Tuple[float, int, int]:
    """R_agencia = active_verbs / passive_verbs"""
    passive_count = 0
    for pattern in PASSIVE_PATTERNS:
        passive_count += len(re.findall(pattern, text.lower()))
    
    # Count active main verbs from spaCy
    active_count = 0
    for token in doc:
        if token.pos_ == "VERB" and token.dep_ in ("ROOT", "ccomp", "xcomp", "advcl"):
            # Check it's not passive
            children_deps = [c.dep_ for c in token.children]
            if "nsubjpass" not in children_deps and "auxpass" not in children_deps:
                active_count += 1
    
    ratio = active_count / max(passive_count, 1)
    return round(ratio, 4), active_count, passive_count


def compute_scientific_links(links: List[str], categories: List[str]) -> float:
    """Ratio of links pointing to scientific concepts vs other topics."""
    if not links and not categories:
        return 0.0
    
    all_items = [l.lower() for l in links] + [c.lower() for c in categories]
    if not all_items:
        return 0.0
    
    scientific_count = sum(
        1 for item in all_items
        if any(sci_kw in item for sci_kw in SCIENTIFIC_CATEGORIES)
    )
    
    return round(scientific_count / len(all_items), 4)


def get_top_adjectives(doc, n: int = 10) -> List[str]:
    adjectives = [
        token.lemma_.lower() for token in doc
        if token.pos_ == "ADJ" and len(token.text) > 3
    ]
    counter = Counter(adjectives)
    return [adj for adj, _ in counter.most_common(n)]


def get_top_nouns(doc, n: int = 10) -> List[str]:
    nouns = [
        token.lemma_.lower() for token in doc
        if token.pos_ == "NOUN" and len(token.text) > 3
    ]
    counter = Counter(nouns)
    return [noun for noun, _ in counter.most_common(n)]


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "nlp-analyzer", "model": nlp.meta.get("name", "unknown")}


@app.post("/analyze", response_model=NLPMetrics)
def analyze_biography(request: NLPRequest):
    """Perform NLP analysis on a biography text."""
    if not request.text or len(request.text.strip()) < 50:
        return NLPMetrics(
            nombre=request.nombre,
            genero=request.genero,
            error="Text too short or empty"
        )

    try:
        # Truncate for spaCy (max ~1M chars)
        text = request.text[:100000]
        
        # Process with spaCy (in chunks if needed)
        doc = nlp(text[:50000])  # spaCy has limits
        
        # Compute all metrics
        domesticity_idx, domestic_found = compute_domesticity_index(text)
        epistemic_count, personality_count, epistemic_density = compute_epistemic_density(doc)
        agency_ratio, active_verbs, passive_verbs = compute_agency_ratio(text, doc)
        scientific_ratio = compute_scientific_links(request.links, request.categories)
        top_adjs = get_top_adjectives(doc)
        top_nouns = get_top_nouns(doc)
        
        sentences = list(doc.sents)
        avg_sentence_length = (
            sum(len(s) for s in sentences) / len(sentences) if sentences else 0
        )
        
        return NLPMetrics(
            nombre=request.nombre,
            genero=request.genero,
            domesticity_index=domesticity_idx,
            epistemic_adjectives_count=epistemic_count,
            personality_adjectives_count=personality_count,
            epistemic_density=epistemic_density,
            agency_ratio=agency_ratio,
            active_verbs=active_verbs,
            passive_verbs=passive_verbs,
            scientific_links_ratio=scientific_ratio,
            top_adjectives=top_adjs,
            top_nouns=top_nouns,
            domestic_keywords_found=domestic_found,
            text_length_tokens=len(doc),
            sentences_count=len(sentences),
            avg_sentence_length=round(avg_sentence_length, 2)
        )

    except Exception as e:
        logger.error(f"NLP analysis error for {request.nombre}: {e}")
        return NLPMetrics(
            nombre=request.nombre,
            genero=request.genero,
            error=str(e)
        )


@app.post("/analyze/batch")
def analyze_batch(requests: List[NLPRequest]):
    """Analyze multiple biographies."""
    results = []
    for req in requests:
        result = analyze_biography(req)
        results.append(result.model_dump())
    return {"results": results}


@app.post("/compare")
def compare_pair(woman: NLPRequest, man: NLPRequest):
    """Compare NLP metrics between a woman and man pair."""
    woman_metrics = analyze_biography(woman)
    man_metrics = analyze_biography(man)
    
    comparison = {
        "woman": woman_metrics.model_dump(),
        "man": man_metrics.model_dump(),
        "differences": {
            "domesticity_delta": round(woman_metrics.domesticity_index - man_metrics.domesticity_index, 4),
            "epistemic_density_delta": round(woman_metrics.epistemic_density - man_metrics.epistemic_density, 4),
            "agency_ratio_delta": round(woman_metrics.agency_ratio - man_metrics.agency_ratio, 4),
            "scientific_links_delta": round(woman_metrics.scientific_links_ratio - man_metrics.scientific_links_ratio, 4),
        }
    }
    return comparison
