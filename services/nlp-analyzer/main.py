"""
NLP Analyzer v6
Improvements over v5:
  - Lexicons loaded from YAML config files (config/lexicons/)
  - Metric 3 (ratio_agencia): enhanced with dependency-based passive detection
    + morphological ser+participio from notebook (combined approach)
  - WordNet-es expansion for adjective classification when available
  - Metric explanation: why a metric can be zero (logged and returned)
  - Domestic lexicon uses lemmas properly — avoids false positives like
    "madre" in "Pedro Duque: nacida" (the word "nacida" is not in DOMESTIC)
  - Configurable semantic expansion via spaCy vectors
"""
import os, re, json, logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from collections import Counter
import yaml
import spacy
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NLP Analyzer v6", version="6.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Config paths ───────────────────────────────────────────────────────────────
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
LEXICON_DIR = CONFIG_DIR / "lexicons"


def load_yaml(path: Path) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ── Load lexicons from YAML ────────────────────────────────────────────────────
def load_domestic_lexicon() -> Tuple[Set[str], List[str]]:
    data = load_yaml(LEXICON_DIR / "domestic.yaml")
    words: Set[str] = set()
    for category, terms in data.items():
        if category in ("version", "compound_terms"):
            continue
        if isinstance(terms, list):
            words.update(t.lower() for t in terms)
    compounds = [c.lower() for c in data.get("compound_terms", [])]
    return words, compounds


def load_epistemic_lexicon() -> Tuple[Set[str], Set[str], Set[str], float]:
    data = load_yaml(LEXICON_DIR / "epistemic.yaml")
    epistemic = set(t.lower() for t in data.get("epistemic", []))
    personality = set(t.lower() for t in data.get("personality", []))
    ignore = set(t.lower() for t in data.get("ignore", []))
    threshold = float(data.get("semantic_expansion_threshold", 0.75))
    return epistemic, personality, ignore, threshold


def load_scientific_keywords() -> List[str]:
    data = load_yaml(LEXICON_DIR / "scientific.yaml")
    return [k.lower() for k in data.get("scientific_keywords", [])]


try:
    DOMESTIC_LEMMAS, DOMESTIC_COMPOUNDS = load_domestic_lexicon()
    ADJ_EPISTEMIC, ADJ_PERSONALITY, ADJ_IGNORE, SEM_THRESHOLD = load_epistemic_lexicon()
    SCIENTIFIC_KW = load_scientific_keywords()
    logger.info(f"Lexicons loaded: {len(DOMESTIC_LEMMAS)} domestic, "
                f"{len(ADJ_EPISTEMIC)} epistemic, {len(ADJ_PERSONALITY)} personality")
except Exception as e:
    logger.error(f"Failed to load lexicons: {e}")
    DOMESTIC_LEMMAS, DOMESTIC_COMPOUNDS = set(), []
    ADJ_EPISTEMIC, ADJ_PERSONALITY, ADJ_IGNORE, SEM_THRESHOLD = set(), set(), set(), 0.75
    SCIENTIFIC_KW = []

# ── Load spaCy model ───────────────────────────────────────────────────────────
nlp = None
NLP_MODEL = "unknown"
for _model in ["es_core_news_lg", "es_core_news_md", "es_core_news_sm"]:
    try:
        nlp = spacy.load(_model)
        NLP_MODEL = _model
        logger.info(f"spaCy loaded: {_model} v{nlp.meta.get('version', '?')}")
        break
    except OSError as e:
        logger.warning(f"Cannot load {_model}: {e}")

if nlp is None:
    raise RuntimeError("No Spanish spaCy model found")

HAS_VECTORS = nlp.vocab.vectors.shape[0] > 0
logger.info(f"Vectors available: {HAS_VECTORS} ({nlp.vocab.vectors.shape})")

# ── WordNet-es expansion ───────────────────────────────────────────────────────
try:
    from nltk.corpus import wordnet as wn
    import nltk
    # Try to use Open Multilingual WordNet for Spanish
    try:
        nltk.data.find('corpora/omw-1.4')
        wn.synsets('brillante', lang='spa')
        HAS_WORDNET = True
        logger.info("WordNet-es (OMW) available for adjective expansion")
    except Exception:
        HAS_WORDNET = False
        logger.info("WordNet-es not available — using lexicon-only classification")
except ImportError:
    HAS_WORDNET = False


def wordnet_expand_epistemic(lemma: str) -> Optional[str]:
    """
    Use WordNet to classify an unknown adjective as 'epistemic' or 'personality'.

    Strategy:
      1. Get synsets for the Spanish lemma (lang='spa' finds synsets containing
         this Spanish word — definitions are always in English in OMW).
      2. Check English definitions using English signal words (correct — definitions
         are in English regardless of input language).
      3. Also check lemma names across all languages in the synset, comparing
         against known Spanish seed sets — this improves coverage significantly
         since OMW includes Spanish synonyms per synset.
    """
    if not HAS_WORDNET:
        return None

    # Spanish seeds for lemma-level matching (complement to English definition signals)
    ep_lemmas_es = {
        "brillante", "inteligente", "sabio", "experto", "talentoso", "competente",
        "hábil", "capaz", "genial", "erudito", "perspicaz", "innovador", "pionero",
        "visionario", "riguroso", "analítico", "preciso", "docto", "versado"
    }
    pers_lemmas_es = {
        "amable", "honesto", "humilde", "trabajador", "dedicado", "generoso",
        "solidario", "valiente", "perseverante", "empático", "modesto", "diligente",
        "tenaz", "cariñoso", "comprometido", "íntegro", "laborioso", "entusiasta"
    }

    # English definition signals (correct to use English here — OMW definitions
    # are always in English, even for synsets found via Spanish lemmas)
    ep_signals   = ["intellig", "intellect", "expert", "knowledge", "wisdom",
                    "skill", "talent", "brilliant", "genius", "capable", "learned",
                    "scholarly", "innovative", "analytical", "precise"]
    pers_signals = ["kind", "friendly", "honest", "hard-working", "diligent",
                    "humble", "modest", "brave", "dedicated", "generous",
                    "empathetic", "loyal", "compassionate", "courageous"]

    try:
        synsets = wn.synsets(lemma, pos=wn.ADJ, lang='spa')
        for syn in synsets:
            # Check 1: English definition (always English in OMW — correct as-is)
            definition = syn.definition().lower()
            if any(s in definition for s in ep_signals):
                return "epistemic"
            if any(s in definition for s in pers_signals):
                return "personality"

            # Check 2: Lemma names in the synset (multilingual — check Spanish ones)
            # This catches cases where the definition is vague but a known Spanish
            # synonym appears in the same synset
            synset_lemmas = set(syn.lemma_names('spa'))  # Spanish synonyms in synset
            if synset_lemmas & ep_lemmas_es:
                return "epistemic"
            if synset_lemmas & pers_lemmas_es:
                return "personality"

    except Exception:
        pass

    return None


def semantic_classify_adj(token) -> Optional[str]:
    """
    Use spaCy word vectors to classify an unknown adjective
    by computing similarity to seed words.
    """
    if not HAS_VECTORS or not token.has_vector:
        return None

    ep_seeds = ["inteligente", "brillante", "experto", "innovador", "talentoso"]
    pers_seeds = ["amable", "trabajador", "honesto", "humilde", "dedicado"]

    try:
        ep_sim = max(
            token.similarity(nlp(seed)[0])
            for seed in ep_seeds
            if nlp(seed)[0].has_vector
        )
        pers_sim = max(
            token.similarity(nlp(seed)[0])
            for seed in pers_seeds
            if nlp(seed)[0].has_vector
        )
        if max(ep_sim, pers_sim) < SEM_THRESHOLD:
            return None
        return "epistemic" if ep_sim >= pers_sim else "personality"
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  METRIC IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_domesticity_index(doc) -> Tuple[float, List[str], str]:
    """
    Notebook implementation + compound detection:
      Id = Σ(lemma in domestic_set) / total_alpha_tokens * 1000

    Returns: (index, keywords_found, explanation)
    Explanation explains why result can be 0.
    """
    total_alpha = 0
    count = 0
    found = set()

    for token in doc:
        if token.is_alpha:
            total_alpha += 1
            lemma = token.lemma_.lower()
            if lemma in DOMESTIC_LEMMAS:
                count += 1
                found.add(lemma)

    # Also check compound terms in the raw text
    text_lower = doc.text.lower()
    for compound in DOMESTIC_COMPOUNDS:
        occurrences = text_lower.count(compound)
        if occurrences > 0:
            count += occurrences
            found.add(compound)

    if total_alpha == 0:
        return 0.0, [], "Texto vacío o sin tokens alfabéticos"

    index = round((count / total_alpha) * 1000, 6)

    if index == 0.0:
        content_lemmas = [
            t.lemma_.lower() for t in doc
            if t.is_alpha and not t.is_stop and len(t.lemma_) > 2
        ]
        top_content = [w for w, _ in Counter(content_lemmas).most_common(8)]
        explanation = (
            f"Ninguno de los {len(DOMESTIC_LEMMAS)} lemas domésticos apareció "
            f"en el texto ({total_alpha} tokens). Esto es esperable en biografías "
            "puramente centradas en logros científicos."
            f"Lemmas de contenido más frecuentes en el texto: {top_content}."
        )
    else:
        explanation = f"{count} ocurrencias en {total_alpha} tokens"

    return index, sorted(found), explanation


def classify_adjective(token) -> Optional[str]:
    """
    Classify a spaCy ADJ token as 'epistemic', 'personality', or None.
    Priority: lexicon > WordNet-es > spaCy vectors > ignore
    """
    lemma = token.lemma_.lower()

    # 1. Ignore list
    if lemma in ADJ_IGNORE:
        return None

    # 2. Direct lexicon match
    if lemma in ADJ_EPISTEMIC:
        return "epistemic"
    if lemma in ADJ_PERSONALITY:
        return "personality"

    # 3. WordNet-es expansion
    wn_result = wordnet_expand_epistemic(lemma)
    if wn_result:
        return wn_result

    # 4. Semantic similarity via spaCy vectors
    sem_result = semantic_classify_adj(token)
    return sem_result


def compute_epistemic_density(doc) -> Tuple[float, int, int, List[str], str]:
    """
    Notebook implementation with enhanced classification:
      D_e = adj_epistemic / (adj_epistemic + adj_personality)

    Returns: (density, ep_count, pers_count, top_adjs, explanation)
    """
    ep_count = 0
    pers_count = 0
    all_adjs = []
    unclassified_adjs = []

    for token in doc:
        if token.pos_ == "ADJ":
            lemma = token.lemma_.lower()
            all_adjs.append(lemma)
            classification = classify_adjective(token)
            if classification == "epistemic":
                ep_count += 1
            elif classification == "personality":
                pers_count += 1
            else:
                unclassified_adjs.append(lemma)

    total = ep_count + pers_count

    if total == 0:
        top_unclassified = [a for a, _ in Counter(unclassified_adjs).most_common(8)]
        explanation = (
            f"No se detectaron adjetivos epistémicos ni de personalidad "
            f"({len(all_adjs)} adjetivos totales detectados). "
            f"Lexicón epistémico: {len(ADJ_EPISTEMIC)} términos, "
            f"personalidad: {len(ADJ_PERSONALITY)} términos. "
            f"Adjetivos no clasificados más frecuentes: {top_unclassified}. "
            "Posible causa: texto corto, léxico especializado no cubierto, "
            "o artículo sin adjetivos valorativos."
        )
        density = 0.0
    else:
        density = round(ep_count / total, 6)
        explanation = (
            f"{ep_count} epistémicos + {pers_count} personalidad = {total} total"
        )

    top = [a for a, _ in Counter(all_adjs).most_common(10)]
    return density, ep_count, pers_count, top, explanation


def compute_agency_ratio(doc) -> Tuple[float, int, int, str]:
    """
    Enhanced agency ratio combining:
      - Notebook method: ser + VerbForm=Part (morphological)
      - Dependency method: nsubjpass / auxpass detection (more robust)

    The combined approach reduces false negatives.
    Returns: (ratio, active_count, passive_count, explanation)
    """
    tokens = list(doc)
    activos = 0
    pasivos = 0

    for i, token in enumerate(tokens):
        if token.pos_ == "VERB":

            # ── Method A: Notebook (morphological) ──
            es_participio = "VerbForm=Part" in str(token.morph)
            tiene_ser_antes = (i > 0 and tokens[i - 1].lemma_ == "ser")
            passive_morph = es_participio and tiene_ser_antes

            # ── Method B: Dependency parsing ──
            # nsubjpass = nominal subject of passive clause
            # auxpass = auxiliary in passive construction
            child_deps = {c.dep_ for c in token.children}
            passive_dep = "nsubjpass" in child_deps or "auxpass" in child_deps

            # ── Combined: passive if EITHER method detects it ──
            if passive_morph or passive_dep:
                pasivos += 1
            else:
                activos += 1

    if pasivos == 0:
        if activos == 0:
            n_tokens = len(tokens)
            n_alpha = sum(1 for t in tokens if t.is_alpha)
            pos_counts = Counter(t.pos_ for t in tokens if t.is_alpha)
            top_pos = ", ".join(f"{p}:{c}" for p, c in pos_counts.most_common(5))
            explanation = (
                f"Texto vacío o sin verbos detectados ({n_tokens} tokens, {n_alpha} alfabéticos). "
                f"POS detectados: [{top_pos}]. "
                "El ratio de agencia no puede calcularse sin verbos. "
                "Verificar que el texto fue extraído correctamente de Wikipedia."
            )
            ratio = 0.0
        else:
            explanation = (
                f"{activos} verbos activos, 0 pasivos. "
                "Ratio devuelto como 0 por convención del notebook "
                "(no como infinito). La ausencia de pasivas indica alta agencia."
            )
            ratio = 0.0
    else:
        ratio = round(activos / pasivos, 6)
        explanation = f"{activos} activos / {pasivos} pasivos"

    return ratio, activos, pasivos, explanation


def compute_scientific_links(links: List[str], categories: List[str]) -> float:
    items = [x.lower() for x in links + categories]
    if not items:
        return 0.0
    sci = sum(1 for i in items if any(k in i for k in SCIENTIFIC_KW))
    return round(sci / len(items), 6)


# ── Pydantic models ────────────────────────────────────────────────────────────

class NLPRequest(BaseModel):
    nombre: str
    genero: str
    text: str
    links: List[str] = []
    categories: List[str] = []


class MetricExplanation(BaseModel):
    value: float
    explanation: str
    is_zero: bool


class NLPMetrics(BaseModel):
    nombre: str
    genero: str
    # Metric values
    domesticity_index: float = 0.0
    epistemic_density: float = 0.0
    agency_ratio: float = 0.0
    scientific_links_ratio: float = 0.0
    # Breakdown
    epistemic_adjectives_count: int = 0
    personality_adjectives_count: int = 0
    active_verbs: int = 0
    passive_verbs: int = 0
    # Top words
    top_adjectives: List[str] = []
    top_nouns: List[str] = []
    domestic_keywords_found: List[str] = []
    # Explanations (why metric is zero if applicable)
    explanation_domesticity: str = ""
    explanation_epistemic: str = ""
    explanation_agency: str = ""
    # Meta
    text_length_tokens: int = 0
    sentences_count: int = 0
    nlp_model: str = NLP_MODEL
    wordnet_available: bool = HAS_WORDNET
    vectors_available: bool = HAS_VECTORS
    error: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "nlp-analyzer",
        "version": "6.0.0",
        "model": NLP_MODEL,
        "wordnet_es": HAS_WORDNET,
        "vectors": HAS_VECTORS,
        "lexicon_sizes": {
            "domestic_lemmas": len(DOMESTIC_LEMMAS),
            "domestic_compounds": len(DOMESTIC_COMPOUNDS),
            "epistemic_adjs": len(ADJ_EPISTEMIC),
            "personality_adjs": len(ADJ_PERSONALITY),
            "scientific_kw": len(SCIENTIFIC_KW),
        }
    }


@app.get("/lexicons")
def get_lexicons():
    """Return current lexicon contents for inspection."""
    return {
        "domestic_lemmas": sorted(DOMESTIC_LEMMAS),
        "domestic_compounds": DOMESTIC_COMPOUNDS,
        "epistemic": sorted(ADJ_EPISTEMIC),
        "personality": sorted(ADJ_PERSONALITY),
        "ignore": sorted(ADJ_IGNORE),
        "scientific_keywords": SCIENTIFIC_KW[:30],
        "semantic_threshold": SEM_THRESHOLD,
    }


@app.post("/analyze", response_model=NLPMetrics)
def analyze(req: NLPRequest):
    if not req.text or len(req.text.strip()) < 30:
        return NLPMetrics(nombre=req.nombre, genero=req.genero,
                          error="Text too short or empty")
    try:
        text = req.text[:80000]
        doc = nlp(text[:50000])  # spaCy processing limit

        did, dom_found, dom_exp = compute_domesticity_index(doc)
        ep_density, ep_count, pers_count, top_adjs, ep_exp = compute_epistemic_density(doc)
        ag_ratio, active_v, passive_v, ag_exp = compute_agency_ratio(doc)
        sci_ratio = compute_scientific_links(req.links, req.categories)

        nouns = [t.lemma_.lower() for t in doc
                 if t.pos_ == "NOUN" and len(t.text) > 3]
        sents = list(doc.sents)

        return NLPMetrics(
            nombre=req.nombre,
            genero=req.genero,
            domesticity_index=did,
            epistemic_density=ep_density,
            agency_ratio=ag_ratio,
            scientific_links_ratio=sci_ratio,
            epistemic_adjectives_count=ep_count,
            personality_adjectives_count=pers_count,
            active_verbs=active_v,
            passive_verbs=passive_v,
            top_adjectives=top_adjs,
            top_nouns=[n for n, _ in Counter(nouns).most_common(10)],
            domestic_keywords_found=dom_found,
            explanation_domesticity=dom_exp,
            explanation_epistemic=ep_exp,
            explanation_agency=ag_exp,
            text_length_tokens=len(doc),
            sentences_count=len(sents),
        )
    except Exception as e:
        logger.error(f"NLP error for {req.nombre}: {e}", exc_info=True)
        return NLPMetrics(nombre=req.nombre, genero=req.genero, error=str(e)[:300])


@app.post("/analyze/batch")
def analyze_batch(reqs: List[NLPRequest]):
    return {"results": [analyze(r).model_dump() for r in reqs]}
