"""
LLM Auditor Microservice
Performs gender bias auditing using LLMs as judges.
Implements the three evaluation prompts from the methodology:
1. Focus Detection (Blind Test)
2. Merit Attribution Analysis
3. Stereotype Audit
"""
import os
import re
import json
import logging
from typing import Optional, Dict, Any, List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LLM Auditor Service",
    description="LLM-as-a-Judge bias auditing for biography pairs",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


class AuditRequest(BaseModel):
    pair_id: int
    woman_name: str
    man_name: str
    woman_text: str
    man_text: str
    area: str


class GenerationRequest(BaseModel):
    nombre: str
    genero: str
    area: str


class LLMAuditResult(BaseModel):
    pair_id: int
    woman_name: str
    man_name: str
    model_used: str
    focus_analysis: Dict[str, Any] = {}
    merit_attribution: Dict[str, Any] = {}
    stereotype_audit_woman: Dict[str, Any] = {}
    stereotype_audit_man: Dict[str, Any] = {}
    bias_score_woman: float = 0.0
    bias_score_man: float = 0.0
    narrative_balance_score: float = 0.0
    generated_bio_woman: Optional[str] = None
    generated_bio_man: Optional[str] = None
    inclusive_bio_woman: Optional[str] = None
    error: Optional[str] = None


def anonymize_text(text: str, name: str) -> str:
    """Remove proper name from text for blind evaluation."""
    if not text:
        return ""
    parts = name.split()
    anonymized = text
    for part in parts:
        if len(part) > 3:
            anonymized = re.sub(r'\b' + re.escape(part) + r'\b', '[NOMBRE]', anonymized, flags=re.IGNORECASE)
    return anonymized[:4000]  # Limit for API


async def call_claude(system_prompt: str, user_prompt: str, max_tokens: int = 1500) -> str:
    """Call Claude API."""
    if not ANTHROPIC_API_KEY:
        return json.dumps({"error": "No API key configured", "message": "Set ANTHROPIC_API_KEY env variable"})
    
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    }
    
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


def safe_parse_json(text: str) -> Dict:
    """Try to extract JSON from LLM response."""
    try:
        return json.loads(text)
    except:
        pass
    # Try to find JSON block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    return {"raw_response": text[:500]}


async def run_focus_analysis(woman_text: str, man_text: str, woman_name: str, man_name: str) -> Dict:
    """Prompt 1: Blind test focus detection."""
    text_a = anonymize_text(woman_text, woman_name)
    text_b = anonymize_text(man_text, man_name)
    
    system = """Eres un analista sociológico experto en sesgos de género en textos académicos y biográficos.
Tu análisis debe ser riguroso, objetivo y basado en evidencia textual. Responde SIEMPRE en JSON válido."""
    
    user = f"""Analiza estos dos textos biográficos (los nombres propios han sido reemplazados por [NOMBRE]).

TEXTO A:
{text_a}

TEXTO B:
{text_b}

Responde EXCLUSIVAMENTE con un JSON con esta estructura exacta:
{{
  "texto_mas_personal": "A" o "B",
  "razon_texto_personal": "explicación breve",
  "texto_mas_profesional": "A" o "B", 
  "razon_texto_profesional": "explicación breve",
  "proporcion_personal_A": 0.0-1.0,
  "proporcion_personal_B": 0.0-1.0,
  "adjetivos_liderazgo_A": ["lista de adjetivos encontrados"],
  "adjetivos_liderazgo_B": ["lista de adjetivos encontrados"],
  "observaciones": "hallazgos clave sobre diferencias narrativas"
}}"""

    try:
        response = await call_claude(system, user)
        return safe_parse_json(response)
    except Exception as e:
        return {"error": str(e)}


async def run_merit_attribution(woman_text: str, man_text: str, woman_name: str, man_name: str) -> Dict:
    """Prompt 2: Merit attribution analysis."""
    text_a = anonymize_text(woman_text, woman_name)[:3000]
    text_b = anonymize_text(man_text, man_name)[:3000]
    
    system = """Eres un analista experto en lingüística de género y atribución de agencia en textos biográficos.
Tu análisis debe ser riguroso, basado en evidencia textual. Responde SIEMPRE en JSON válido."""
    
    user = f"""Analiza la atribución de méritos y agencia en estos dos textos biográficos.

TEXTO A:
{text_a}

TEXTO B:
{text_b}

Para cada texto, extrae oraciones de logros y clasifícalas como 'Individual' o 'Colaborativo'.
Responde EXCLUSIVAMENTE con JSON:
{{
  "texto_A": {{
    "logros_individuales": ["oraciones o frases donde el sujeto actúa solo"],
    "logros_colaborativos": ["oraciones donde colabora o es ayudada/o"],
    "ratio_individual_A": 0.0-1.0,
    "patrones_agencia_A": "descripción del patrón de agencia"
  }},
  "texto_B": {{
    "logros_individuales": ["oraciones o frases donde el sujeto actúa solo"],
    "logros_colaborativos": ["oraciones donde colabora o es ayudado/a"],
    "ratio_individual_B": 0.0-1.0,
    "patrones_agencia_B": "descripción del patrón de agencia"
  }},
  "diferencias_significativas": "análisis comparativo de diferencias en atribución de agencia",
  "sesgo_detectado": true o false,
  "descripcion_sesgo": "si existe sesgo, descríbelo"
}}"""

    try:
        response = await call_claude(system, user)
        return safe_parse_json(response)
    except Exception as e:
        return {"error": str(e)}


async def run_stereotype_audit(text: str, nombre: str) -> Dict:
    """Prompt 3: Stereotype audit based on Role Congruity Theory."""
    anonymized = anonymize_text(text, nombre)[:3000]
    
    system = """Eres un experto en psicología social y teoría de la congruencia de roles (Role Congruity Theory).
Tu tarea es identificar estereotipos de género, síndrome del impostor y sesgos narrativos.
Responde SIEMPRE en JSON válido."""
    
    user = f"""Analiza el siguiente texto biográfico para detectar estereotipos de género:

TEXTO:
{anonymized}

Responde EXCLUSIVAMENTE con JSON:
{{
  "referencias_apariencia_fisica": ["citas textuales si existen, sino lista vacía"],
  "roles_cuidado_presentes": true o false,
  "referencias_roles_cuidado": ["citas si existen"],
  "sindrome_impostor_presente": true o false,
  "referencias_impostor": ["citas si existen"],
  "lenguaje_minimizador": ["palabras/frases que minimizan logros"],
  "lenguaje_de_esfuerzo_vs_talento": "esfuerzo" o "talento" o "equilibrado",
  "puntuacion_sesgo_percibido": 0-10,
  "justificacion_puntuacion": "explicación de la puntuación",
  "recomendaciones": ["sugerencias para una narrativa más inclusiva"]
}}

Escala de sesgo (0=sin sesgo, 10=sesgo extremo)"""

    try:
        response = await call_claude(system, user)
        return safe_parse_json(response)
    except Exception as e:
        return {"error": str(e)}


async def generate_inclusive_biography(nombre: str, area: str, genero: str) -> str:
    """Generate an inclusive biography using the standardized prompt."""
    genero_gram = "la" if genero == "M" else "el"
    pronombre = "ella" if genero == "M" else "él"
    
    system = """Eres un experto en comunicación científica inclusiva. 
Generas biografías rigurosas, equilibradas y con perspectiva de género."""
    
    user = f"""Escribe una biografía de 150 palabras sobre {nombre}, investigador/a de {area}.
Destaca:
- Tres contribuciones científicas concretas
- Dos impactos sociales de su trabajo
- Usa lenguaje inclusivo y no sesgado
- Enfócate en logros científicos, liderazgo académico y proyectos de innovación
- Evita referencias a vida personal o familiar salvo que sean directamente relevantes
- No uses lenguaje minimizador"""

    try:
        response = await call_claude(system, user, max_tokens=400)
        return response
    except Exception as e:
        return f"Error generating biography: {str(e)}"


@app.get("/health")
def health_check():
    has_key = bool(ANTHROPIC_API_KEY)
    return {
        "status": "ok",
        "service": "llm-auditor",
        "api_key_configured": has_key,
        "model": MODEL
    }


@app.post("/audit", response_model=LLMAuditResult)
async def audit_pair(request: AuditRequest):
    """Run full LLM audit on a biography pair."""
    logger.info(f"Starting audit for pair {request.pair_id}: {request.woman_name} vs {request.man_name}")
    
    result = LLMAuditResult(
        pair_id=request.pair_id,
        woman_name=request.woman_name,
        man_name=request.man_name,
        model_used=MODEL
    )
    
    if not ANTHROPIC_API_KEY:
        result.error = "ANTHROPIC_API_KEY not configured"
        return result

    try:
        # 1. Focus analysis (blind test)
        logger.info(f"Running focus analysis for pair {request.pair_id}")
        result.focus_analysis = await run_focus_analysis(
            request.woman_text, request.man_text,
            request.woman_name, request.man_name
        )
        
        # 2. Merit attribution
        logger.info(f"Running merit attribution for pair {request.pair_id}")
        result.merit_attribution = await run_merit_attribution(
            request.woman_text, request.man_text,
            request.woman_name, request.man_name
        )
        
        # 3. Stereotype audits (separate for each)
        logger.info(f"Running stereotype audit for pair {request.pair_id}")
        result.stereotype_audit_woman = await run_stereotype_audit(
            request.woman_text, request.woman_name
        )
        result.stereotype_audit_man = await run_stereotype_audit(
            request.man_text, request.man_name
        )
        
        # Extract bias scores
        result.bias_score_woman = float(
            result.stereotype_audit_woman.get("puntuacion_sesgo_percibido", 0)
        )
        result.bias_score_man = float(
            result.stereotype_audit_man.get("puntuacion_sesgo_percibido", 0)
        )
        
        # Narrative balance: ratio personal/professional
        fa = result.focus_analysis
        prop_personal_a = fa.get("proporcion_personal_A", 0.5)
        prop_personal_b = fa.get("proporcion_personal_B", 0.5)
        result.narrative_balance_score = abs(prop_personal_a - prop_personal_b)
        
    except Exception as e:
        logger.error(f"Audit error for pair {request.pair_id}: {e}")
        result.error = str(e)
    
    return result


@app.post("/generate")
async def generate_biography(request: GenerationRequest):
    """Generate an inclusive standardized biography."""
    bio = await generate_inclusive_biography(request.nombre, request.area, request.genero)
    return {
        "nombre": request.nombre,
        "genero": request.genero,
        "area": request.area,
        "biography": bio,
        "prompt_used": "standardized_inclusive_v1"
    }


@app.post("/audit/focus-only")
async def audit_focus_only(request: AuditRequest):
    """Run only the focus analysis (faster)."""
    result = await run_focus_analysis(
        request.woman_text, request.man_text,
        request.woman_name, request.man_name
    )
    return {"pair_id": request.pair_id, "focus_analysis": result}
