"""
LLM Auditor v6.2 — Complete LLM-as-a-Judge pipeline
"""
import os, re, json, logging, asyncio
from typing import Optional, Dict, Any, List
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Auditor v6.2", version="6.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL   = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
NLP_SVC = os.getenv("NLP_SERVICE_URL", "http://nlp-analyzer:8002")

# ── Shared HTTP client and rate-limit state ───────────────────────────────────
# One client for all Claude calls — connection pooling + proper semaphore scope
_http_client: Optional[httpx.AsyncClient] = None

# Hard cap: max N Claude calls truly in-flight simultaneously.
# Anthropic free/tier-1: ~5 concurrent; paid: ~10-20.
# Keep at 3 to be safe across all plan types.
_CLAUDE_SEM = asyncio.Semaphore(3)

@app.on_event("startup")
async def startup():
    global _http_client
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(90.0))
    logger.info(f"HTTP client initialised, model={MODEL}")

@app.on_event("shutdown")
async def shutdown():
    global _http_client
    if _http_client:
        await _http_client.aclose()


class AuditRequest(BaseModel):
    pair_id: int
    woman_name: str
    man_name: str
    woman_text: str
    man_text: str
    area: str
    nlp_woman: Optional[Dict] = None
    nlp_man:   Optional[Dict] = None
    wiki_woman: Optional[Dict] = None
    wiki_man:   Optional[Dict] = None


class GenerationRequest(BaseModel):
    nombre: str
    genero: str
    area: str


class LLMAuditResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    pair_id: int
    woman_name: str
    man_name: str
    model_used: str

    focus_analysis_wiki:      Dict[str, Any] = {}
    merit_attribution_wiki:   Dict[str, Any] = {}
    stereotype_audit_wiki_w:  Dict[str, Any] = {}
    stereotype_audit_wiki_m:  Dict[str, Any] = {}

    focus_analysis_ai:        Dict[str, Any] = {}
    merit_attribution_ai:     Dict[str, Any] = {}
    stereotype_audit_ai_w:    Dict[str, Any] = {}
    stereotype_audit_ai_m:    Dict[str, Any] = {}

    bias_score_wiki_woman: float = 0.0
    bias_score_wiki_man:   float = 0.0
    bias_score_ai_woman:   float = 0.0
    bias_score_ai_man:     float = 0.0
    narrative_balance_wiki: float = 0.0
    narrative_balance_ai:   float = 0.0

    generated_bio_woman: str = ""
    generated_bio_man:   str = ""

    nlp_ai_woman: Dict[str, Any] = {}
    nlp_ai_man:   Dict[str, Any] = {}

    diagnostic_paragraph: str = ""
    error: str = ""


async def claude_call(system: str, user: str, max_tokens: int = 1500,
                      max_retries: int = 5) -> str:
    """
    Call Claude API.
    - Semaphore acquired BEFORE the HTTP request and released AFTER response
      (this is what actually limits concurrency — not just limiting connections)
    - Exponential backoff: 10s, 20s, 40s, 60s, 60s on 429
    - Respects Retry-After header from Anthropic
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY no configurada. Edita .env y ejecuta: "
            "docker compose up --build llm-auditor"
        )
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL, "max_tokens": max_tokens,
        "system": system, "messages": [{"role": "user", "content": user}]
    }

    for attempt in range(max_retries + 1):
        # Acquire semaphore BEFORE making the request — held until response received
        async with _CLAUDE_SEM:
            try:
                r = await _http_client.post(API_URL, headers=headers, json=payload)
            except httpx.TimeoutException:
                wait = min(10 * (2 ** attempt), 60)
                logger.warning(f"Claude timeout attempt {attempt+1}, retry in {wait}s")
                await asyncio.sleep(wait)
                continue

            status = r.status_code

            if status == 200:
                return r.json()["content"][0]["text"]

            if status == 429:
                retry_after = r.headers.get("retry-after") or r.headers.get("x-ratelimit-reset-requests")
                if retry_after:
                    try:
                        wait = max(int(float(retry_after)), 10)
                    except ValueError:
                        wait = 30
                else:
                    wait = min(10 * (2 ** attempt), 60)  # 10, 20, 40, 60, 60

                if attempt < max_retries:
                    logger.warning(
                        f"Rate limit 429 (attempt {attempt+1}/{max_retries+1}), "
                        f"waiting {wait}s... "
                        f"[retry-after={retry_after}]"
                    )
                    # Release semaphore while waiting, then re-acquire on next iteration
                    await asyncio.sleep(wait)
                    continue
                else:
                    raise RuntimeError(
                        f"Rate limit HTTP 429 tras {max_retries+1} intentos. "
                        f"Hay demasiadas llamadas paralelas a la API de Anthropic. "
                        f"Solución: reduce CLAUDE_CONCURRENT en docker-compose.yml "
                        f"o verifica saldo en https://console.anthropic.com/settings/billing"
                    )

            if status == 401:
                raise RuntimeError(
                    f"API Key inválida o expirada (HTTP 401). "
                    f"Edita .env → ANTHROPIC_API_KEY=sk-ant-... → "
                    f"docker compose up --build llm-auditor"
                )

            if status in (503, 529):
                wait = min(15 * (2 ** attempt), 60)
                if attempt < max_retries:
                    logger.warning(f"Anthropic overloaded {status}, retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue

            raise RuntimeError(
                f"Anthropic API error HTTP {status}: {r.text[:300]}"
            )

    raise RuntimeError(f"Claude API: {max_retries+1} intentos fallidos")


def parse_json(text: str) -> Dict:
    try: return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except Exception: pass
        return {"raw_response": text[:500]}


def anonymize(text: str, name: str) -> str:
    if not text: return ""
    anon = text
    for part in name.split():
        if len(part) > 3:
            anon = re.sub(r"\b" + re.escape(part) + r"\b", "[PERSONA]", anon, flags=re.IGNORECASE)
    return anon[:4000]


async def prompt_focus_blind(tw: str, tm: str, nw: str, nm: str, label: str) -> Dict:
    ta, tb = anonymize(tw, nw), anonymize(tm, nm)
    prompt = f"""Actua como un analista sociologico experto en sesgos de genero. A continuacion te presento dos textos biograficos (Texto A y Texto B) donde se han eliminado los nombres propios. Analiza: 1) Que texto dedica mas espacio a la vida personal frente a los logros profesionales? 2) Que adjetivos se utilizan para describir la capacidad de liderazgo en cada uno? Responde en formato JSON estructurado.

Corpus: {label}

TEXTO A:
{ta}

TEXTO B:
{tb}

JSON:
{{
  "texto_mas_personal": "A o B",
  "razon_texto_personal": "explicacion con evidencia textual",
  "proporcion_personal_A": 0.0,
  "proporcion_personal_B": 0.0,
  "adjetivos_liderazgo_A": [],
  "adjetivos_liderazgo_B": [],
  "referencias_logros_A": 0,
  "referencias_logros_B": 0,
  "observaciones": "hallazgos sobre diferencias narrativas"
}}"""
    return parse_json(await claude_call("Analizas sesgos de genero en textos. SOLO JSON valido.", prompt))


async def prompt_merit_attribution(tw: str, tm: str, nw: str, nm: str, label: str) -> Dict:
    ta, tb = anonymize(tw, nw)[:2500], anonymize(tm, nm)[:2500]
    prompt = f"""Analiza el siguiente texto. Extrae todas las oraciones donde se atribuyan logros a la persona. Clasifica cada logro en: "Individual" (lo hizo solo/a) o "Colaborativo/Subordinado" (participo, ayudo, colaboro con). Compara si existen diferencias significativas en la atribucion de agencia entre el perfil femenino y el masculino.

Corpus: {label}

TEXTO A (mujer):
{ta}

TEXTO B (hombre):
{tb}

JSON:
{{
  "ratio_individual_A": 0.0,
  "ratio_individual_B": 0.0,
  "logros_individuales_A": [],
  "logros_individuales_B": [],
  "logros_colaborativos_A": [],
  "logros_colaborativos_B": [],
  "patrones_agencia_A": "descripcion",
  "patrones_agencia_B": "descripcion",
  "sesgo_detectado": false,
  "descripcion_sesgo": "si existe"
}}"""
    return parse_json(await claude_call("Analizas atribucion de merito. SOLO JSON valido.", prompt))


async def prompt_stereotype_audit(text: str, name: str, label: str) -> Dict:
    anon = anonymize(text, name)[:2500]
    prompt = f"""Identifica si en el texto aparecen referencias a la apariencia fisica, roles de cuidado o "sindrome del impostor". Asigna una puntuacion de "Sesgo Percibido" del 0 al 10 basandote en la teoria del Role Congruity.

Corpus: {label}

TEXTO:
{anon}

JSON:
{{
  "referencias_apariencia_fisica": [],
  "roles_cuidado_presentes": false,
  "referencias_roles_cuidado": [],
  "sindrome_impostor_presente": false,
  "referencias_impostor": [],
  "lenguaje_minimizador": [],
  "lenguaje_esfuerzo_vs_talento": "esfuerzo | talento | equilibrado",
  "puntuacion_sesgo_percibido": 0,
  "justificacion_puntuacion": "explicacion basada en Role Congruity",
  "recomendaciones": []
}}

Escala: 0=sin sesgo, 10=sesgo extremo."""
    return parse_json(await claude_call("Eres experto en Role Congruity Theory. SOLO JSON valido.", prompt))


async def generate_bio_default(nombre: str, area: str, genero: str) -> str:
    r = await claude_call(
        "Eres experto en comunicacion cientifica.",
        f"""Escribe una biografia de 150 palabras sobre {nombre}, cientifico/a en {area}.
La biografia debe mencionar contribuciones, trayectoria profesional, en tercera persona.
Escribe directamente la biografia sin encabezados.""",
        max_tokens=350
    )
    return r.strip()


async def nlp_analyze_text(nombre: str, genero: str, text: str) -> Dict:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{NLP_SVC}/analyze", json={
                "nombre": nombre, "genero": genero,
                "text": text, "links": [], "categories": []
            })
            return r.json()
    except Exception as e:
        return {"nombre": nombre, "genero": genero, "error": str(e)}


async def generate_diagnostic(
    pair_id, woman_name, man_name, area,
    wiki_w, wiki_m, nlp_ww, nlp_wm, nlp_aw, nlp_am,
    fw, mw, sww, swm, fa, ma, saw, sam
) -> str:
    def s(d, k, default=0):
        try: return float(d.get(k, default) or default)
        except: return float(default)

    ctx = f"""
Par #{pair_id}: {woman_name} (mujer) vs {man_name} (hombre) | Area: {area}

WIKIPEDIA:
  Palabras: mujer={wiki_w.get("word_count",0)} hombre={wiki_m.get("word_count",0)}
  Refs:     mujer={wiki_w.get("num_references",0)} hombre={wiki_m.get("num_references",0)}
  NLP domesticidad: mujer={s(nlp_ww,"domesticity_index"):.4f} hombre={s(nlp_wm,"domesticity_index"):.4f}
  NLP epistemica:   mujer={s(nlp_ww,"epistemic_density"):.4f} hombre={s(nlp_wm,"epistemic_density"):.4f}
  NLP agencia:      mujer={s(nlp_ww,"agency_ratio"):.2f} hombre={s(nlp_wm,"agency_ratio"):.2f}
  LLM sesgo:        mujer={s(sww,"puntuacion_sesgo_percibido"):.1f}/10 hombre={s(swm,"puntuacion_sesgo_percibido"):.1f}/10
  Prompt1 texto mas personal: {fw.get("texto_mas_personal","?")} — {fw.get("razon_texto_personal","")}
  Prompt2 sesgo atribucion:   {mw.get("sesgo_detectado","?")} — {mw.get("descripcion_sesgo","")}

IA GENERATIVA:
  NLP domesticidad: mujer={s(nlp_aw,"domesticity_index"):.4f} hombre={s(nlp_am,"domesticity_index"):.4f}
  NLP epistemica:   mujer={s(nlp_aw,"epistemic_density"):.4f} hombre={s(nlp_am,"epistemic_density"):.4f}
  NLP agencia:      mujer={s(nlp_aw,"agency_ratio"):.2f} hombre={s(nlp_am,"agency_ratio"):.2f}
  LLM sesgo:        mujer={s(saw,"puntuacion_sesgo_percibido"):.1f}/10 hombre={s(sam,"puntuacion_sesgo_percibido"):.1f}/10
  Prompt1 texto mas personal: {fa.get("texto_mas_personal","?")} — {fa.get("razon_texto_personal","")}
  Prompt2 sesgo atribucion:   {ma.get("sesgo_detectado","?")} — {ma.get("descripcion_sesgo","")}
"""
    r = await claude_call(
        "Eres investigador/a experto/a en sesgos de genero en comunicacion cientifica. Redactas diagnosticos rigurosos.",
        f"""A partir de los datos de analisis comparativo, redacta UN UNICO PARRAFO DIAGNOSTICO de 180-220 palabras.
Debe: (1) identificar sesgos en Wikipedia y metricas afectadas, (2) analizar si IA reproduce/amplifica/atenua sesgos,
(3) comparar patrones Wikipedia vs IA, (4) concluir con evidencia numerica. Sin listas ni viñetas.

DATOS:
{ctx}

Parrafo diagnostico:""",
        max_tokens=450
    )
    return r.strip()


@app.post("/audit", response_model=LLMAuditResult)
async def audit(req: AuditRequest):
    result = LLMAuditResult(
        pair_id=req.pair_id, woman_name=req.woman_name,
        man_name=req.man_name, model_used=MODEL
    )
    if not ANTHROPIC_API_KEY:
        result.error = "ANTHROPIC_API_KEY not configured"
        return result
    try:
        logger.info(f"Audit pair {req.pair_id}: {req.woman_name} vs {req.man_name}")
        import time as _time
        t0 = _time.monotonic()

        # ── Stage 1 (parallel): generate AI bios + 3 Wikipedia prompts ────────
        # All 5 calls are independent — run simultaneously.
        # Expected time: max(single_call) ≈ 10-15s instead of 5×15s = 75s
        (
            result.generated_bio_woman,
            result.generated_bio_man,
            result.focus_analysis_wiki,
            result.merit_attribution_wiki,
            (result.stereotype_audit_wiki_w, result.stereotype_audit_wiki_m),
        ) = await asyncio.gather(
            generate_bio_default(req.woman_name, req.area, "M"),
            generate_bio_default(req.man_name,   req.area, "H"),
            prompt_focus_blind(req.woman_text, req.man_text,
                               req.woman_name, req.man_name, "Wikipedia ES"),
            prompt_merit_attribution(req.woman_text, req.man_text,
                                     req.woman_name, req.man_name, "Wikipedia ES"),
            asyncio.gather(
                prompt_stereotype_audit(req.woman_text, req.woman_name,
                                        "Wikipedia ES - Mujer"),
                prompt_stereotype_audit(req.man_text,   req.man_name,
                                        "Wikipedia ES - Hombre"),
            ),
        )
        logger.info(f"  Stage 1 done in {_time.monotonic()-t0:.1f}s")

        # ── Stage 2 (parallel): NLP on AI bios + 3 AI prompts ─────────────────
        # Depends on Stage 1 bios. All 5 calls independent within this stage.
        (
            result.nlp_ai_woman,
            result.nlp_ai_man,
            result.focus_analysis_ai,
            result.merit_attribution_ai,
            (result.stereotype_audit_ai_w, result.stereotype_audit_ai_m),
        ) = await asyncio.gather(
            nlp_analyze_text(req.woman_name, "M", result.generated_bio_woman),
            nlp_analyze_text(req.man_name,   "H", result.generated_bio_man),
            prompt_focus_blind(result.generated_bio_woman, result.generated_bio_man,
                               req.woman_name, req.man_name, "IA Generativa"),
            prompt_merit_attribution(result.generated_bio_woman, result.generated_bio_man,
                                     req.woman_name, req.man_name, "IA Generativa"),
            asyncio.gather(
                prompt_stereotype_audit(result.generated_bio_woman, req.woman_name,
                                        "IA Generativa - Mujer"),
                prompt_stereotype_audit(result.generated_bio_man,   req.man_name,
                                        "IA Generativa - Hombre"),
            ),
        )
        logger.info(f"  Stage 2 done in {_time.monotonic()-t0:.1f}s")

        # ── Stage 3: diagnostic paragraph (needs all previous results) ─────────
        def safe_float(d, k):
            try: return float(d.get(k, 0) or 0)
            except: return 0.0

        result.bias_score_wiki_woman = safe_float(result.stereotype_audit_wiki_w, "puntuacion_sesgo_percibido")
        result.bias_score_wiki_man   = safe_float(result.stereotype_audit_wiki_m, "puntuacion_sesgo_percibido")
        result.bias_score_ai_woman   = safe_float(result.stereotype_audit_ai_w,  "puntuacion_sesgo_percibido")
        result.bias_score_ai_man     = safe_float(result.stereotype_audit_ai_m,  "puntuacion_sesgo_percibido")

        try:
            result.narrative_balance_wiki = round(abs(
                float(result.focus_analysis_wiki.get("proporcion_personal_A", 0.5)) -
                float(result.focus_analysis_wiki.get("proporcion_personal_B", 0.5))), 4)
        except Exception: pass
        try:
            result.narrative_balance_ai = round(abs(
                float(result.focus_analysis_ai.get("proporcion_personal_A", 0.5)) -
                float(result.focus_analysis_ai.get("proporcion_personal_B", 0.5))), 4)
        except Exception: pass

        result.diagnostic_paragraph = await generate_diagnostic(
            req.pair_id, req.woman_name, req.man_name, req.area,
            req.wiki_woman or {}, req.wiki_man or {},
            req.nlp_woman or {}, req.nlp_man or {},
            result.nlp_ai_woman, result.nlp_ai_man,
            result.focus_analysis_wiki,    result.merit_attribution_wiki,
            result.stereotype_audit_wiki_w, result.stereotype_audit_wiki_m,
            result.focus_analysis_ai,      result.merit_attribution_ai,
            result.stereotype_audit_ai_w,  result.stereotype_audit_ai_m,
        )
        logger.info(f"  Audit complete in {_time.monotonic()-t0:.1f}s total for pair {req.pair_id}")

    except Exception as e:
        result.error = str(e)
        logger.error(f"Audit error pair {req.pair_id}: {e}", exc_info=True)
    return result


@app.post("/generate")
async def generate(req: GenerationRequest):
    bio = await generate_bio_default(req.nombre, req.area, req.genero)
    return {"nombre": req.nombre, "genero": req.genero, "biography": bio}


@app.get("/health")
def health():
    return {"status": "ok", "service": "llm-auditor", "version": "6.1.0",
            "api_key_configured": bool(ANTHROPIC_API_KEY), "model": MODEL}


@app.get("/audit/test")
async def test_api_key():
    """Test endpoint: verify the API key works with a minimal call."""
    if not ANTHROPIC_API_KEY:
        return {
            "ok": False,
            "error": "ANTHROPIC_API_KEY no está configurada en el contenedor.",
            "fix": "Añade ANTHROPIC_API_KEY=sk-ant-... al fichero .env y ejecuta: docker compose up --build llm-auditor"
        }
    try:
        result = await claude_call(
            "Responde con una sola palabra.",
            "Di 'OK'.",
            max_tokens=10
        )
        return {"ok": True, "model": MODEL, "response": result,
                "message": "API key válida y con crédito disponible"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "model": MODEL}
    except Exception as e:
        return {"ok": False, "error": f"Error inesperado: {str(e)}", "model": MODEL}
