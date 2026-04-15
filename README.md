# 🔬 Wikipedia Bias Analyzer

**Análisis comparativo de sesgos de género en biografías de Wikipedia**  
Premio Ada Byron · Universidad de Deusto · Jesuit Universities Global Research Alliance

---

## 📐 Arquitectura de Microservicios

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cliente / Navegador                       │
│                     http://localhost:8080                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │    Frontend        │  :8080
                    │  Dashboard Web     │  FastAPI + HTML/JS
                    └─────────┬─────────┘
                              │ REST
                    ┌─────────▼─────────┐
                    │   API Gateway      │  :8000
                    │   Orchestrador     │  FastAPI
                    └──┬─────┬──────┬───┘
                       │     │      │
          ┌────────────▼┐  ┌─▼──────▼──┐  ┌───────────────┐
          │  Wikipedia  │  │    NLP     │  │  LLM Auditor  │
          │  Extractor  │  │  Analyzer  │  │  (Claude API) │
          │    :8001    │  │   :8002    │  │    :8003      │
          │  wikipedia  │  │   spaCy    │  │  Anthropic    │
          │    -api     │  │   es_lg    │  │    claude-    │
          │  (cache en  │  │            │  │   sonnet-4    │
          │   volumen)  │  │            │  │               │
          └─────────────┘  └────────────┘  └───────────────┘
```

### Servicios

| Servicio | Puerto | Función | Tecnologías |
|---|---|---|---|
| `frontend` | 8080 | Dashboard interactivo | FastAPI, Chart.js, HTML/CSS/JS |
| `api-gateway` | 8000 | Orquestador, endpoints unificados | FastAPI, httpx async |
| `wikipedia-extractor` | 8001 | Extracción y caché de Wikipedia | FastAPI, wikipedia-api, httpx |
| `nlp-analyzer` | 8002 | Análisis lingüístico NLP | FastAPI, spaCy es_core_news_lg |
| `llm-auditor` | 8003 | Auditoría LLM-as-a-Judge | FastAPI, Anthropic API |

---

## 🚀 Arranque (un solo comando)

### Prerrequisitos
- Docker ≥ 24.0
- Docker Compose ≥ 2.20
- ~4 GB de RAM disponible (spaCy necesita memoria)
- Conexión a internet (para Wikipedia y, opcionalmente, Anthropic API)

### 1. Clonar / situar los ficheros

```bash
cd wikipedia-bias-analyzer/
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env y añade tu ANTHROPIC_API_KEY si quieres usar la auditoría LLM
```

### 3. Arrancar todo con un solo comando

```bash
docker-compose up --build
```

> La primera vez tardará 5–10 minutos en descargarse el modelo spaCy `es_core_news_lg` (~570 MB).

### 4. Abrir el Dashboard

```
http://localhost:8080
```

### Parar los servicios

```bash
docker-compose down
# Para eliminar también los volúmenes de datos y caché:
docker-compose down -v
```

---

## 📊 Metodología Implementada

### Métricas Cuantitativas (Wikipedia)

Extraídas automáticamente vía `wikipedia-api` + MediaWiki REST API:

| Métrica | Descripción |
|---|---|
| Longitud (palabras) | `len(page.content.split())` |
| Nº Referencias | Conteo de `<li id="cite_note...">` en HTML |
| Nº Enlaces internos | `len(page.links)` |
| Nº Categorías | `len(page.categories)` |
| Nº Imágenes | `len(page.images)` |
| Fecha de creación | MediaWiki API `rvdir=newer&rvlimit=1` |

### Métricas NLP (spaCy `es_core_news_lg`)

| Métrica | Fórmula |
|---|---|
| **Índice de Domesticidad (Iᵈ)** | `Σ(keywords_domésticos) / N × 1000` |
| **Densidad Epistémica** | `adj_intelecto / (adj_intelecto + adj_personalidad)` |
| **Ratio de Agencia** | `R = verbos_activos / verbos_pasivos` |
| **Centralidad enlaces científicos** | `links_científicos / total_links` |

### Auditoría LLM (3 Prompts Controlados)

1. **Blind Test de Foco** — Los textos se anonimizan (nombres → `[NOMBRE]`) y se analiza qué texto tiene más peso en vida personal vs. logros profesionales.

2. **Atribución de Mérito** — Clasifica logros como `Individual` o `Colaborativo/Subordinado` y detecta diferencias de agencia entre pares.

3. **Auditoría de Estereotipos** — Basado en la teoría de Role Congruity, asigna una puntuación de sesgo percibido (0–10) e identifica referencias a apariencia, roles de cuidado o síndrome del impostor.

---

## 🌐 API Reference

### API Gateway (`:8000`)

```
GET  /health                        — Estado de todos los servicios
GET  /pairs                         — Lista de 20 pares biográficos
POST /analyze/start?run_llm=false   — Inicia análisis completo (background)
POST /analyze/pair/{pair_id}        — Analiza un par concreto
GET  /analyze/status                — Estado y progreso del análisis
GET  /results                       — Todos los resultados
GET  /results/valid                 — Solo pares con ambos en Wikipedia ES
GET  /results/skipped               — Pares omitidos (falta Wikipedia)
GET  /results/summary               — Estadísticas agregadas comparativas
DELETE /results                     — Limpia resultados y caché de estado
```

### Wikipedia Extractor (`:8001`)

```
POST /extract                       — Extrae métricas de una biografía
POST /extract/batch                 — Extrae para lista de biografías
GET  /extract/{nombre}              — Recupera resultado cacheado
GET  /cache/list                    — Lista entradas en caché
DELETE /cache/{nombre}              — Elimina entrada de caché
```

### NLP Analyzer (`:8002`)

```
POST /analyze                       — Análisis NLP de un texto
POST /analyze/batch                 — Análisis para múltiples textos
POST /compare                       — Compara par mujer/hombre directamente
```

### LLM Auditor (`:8003`)

```
POST /audit                         — Auditoría completa de un par (3 prompts)
POST /audit/focus-only              — Solo el blind test de foco
POST /generate                      — Genera biografía inclusiva de referencia
```

---

## 📂 Estructura del Proyecto

```
wikipedia-bias-analyzer/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── services/
    ├── wikipedia-extractor/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── main.py            # Extracción Wikipedia + caché
    ├── nlp-analyzer/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── main.py            # spaCy: Id, densidad epistémica, agencia
    ├── llm-auditor/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── main.py            # 3 prompts de auditoría + generación
    ├── api-gateway/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── main.py            # Orquestador + pipeline completo
    └── frontend/
        ├── Dockerfile
        ├── requirements.txt
        └── main.py            # Dashboard HTML/JS interactivo
```

---

## ⚙️ Flujo de Análisis

```
Para cada par (mujer, hombre):
  1. Wikipedia Extractor
     ├── Busca artículo en Wikipedia ES
     ├── Si NO existe alguno de los dos → pair.skipped = True → siguiente
     └── Si existen ambos → extrae métricas cuantitativas + raw_text

  2. NLP Analyzer (parallel para mujer y hombre)
     ├── Calcula Índice de Domesticidad
     ├── Calcula Densidad Epistémica (adjetivos)
     ├── Calcula Ratio de Agencia (voz activa/pasiva)
     └── Calcula Centralidad de enlaces científicos

  3. LLM Auditor (opcional, requiere ANTHROPIC_API_KEY)
     ├── Prompt 1: Blind Test de Foco (textos anonimizados)
     ├── Prompt 2: Atribución de Mérito (individual vs colaborativo)
     └── Prompt 3: Auditoría de estereotipos (Role Congruity, 0-10)

  → Resultados persistidos en volumen Docker (results.json)
```

---

## 🔑 Uso sin API Key de Anthropic

La auditoría LLM es **opcional**. Sin API key, el sistema realiza igualmente:
- Extracción completa de Wikipedia
- Análisis NLP con spaCy
- Dashboard con todas las métricas cuantitativas

Para activar la auditoría LLM:
1. Añade `ANTHROPIC_API_KEY=sk-ant-...` en el fichero `.env`
2. En el dashboard, haz clic en **"Análisis Completo (incl. LLM)"**
3. O usa el parámetro `?run_llm=true` en `POST /analyze/start`

---

## 📋 Pares Biográficos (Premio Ada Byron)

| Par | Mujer | Hombre | Área |
|---|---|---|---|
| 1 | Montserrat Meya | Ramón López de Mántaras | Lingüística computacional / IA |
| 2 | Asunción Gómez-Pérez | Carles Sierra | Web semántica / Ontologías |
| 3 | Nuria Oliver | Mateo Valero | IA / Big Data / Supercomputación |
| 4 | Regina Llopis Rivas | Andrés Pedreño | IA aplicada / Economía digital |
| 5 | María Ángeles Martín Prats | Pedro Duque | Ingeniería aeroespacial |
| 6 | Concha Monje | José Luis Pons | Robótica |
| 7 | Laura Lechuga | Luis Liz-Marzán | Nanociencia / Biosensores |
| 8 | Elena García Armada | José Luis López Gómez | Exoesqueletos / Ingeniería |
| 9 | Lourdes Verdes-Montenegro | José Cernicharo | Radioastronomía / Astrofísica |
| 10 | María José Escalona | Manuel Hermenegildo | Ingeniería del software |
| 11 | Julia G. Niso | Gustavo Deco | Neuroingeniería |
| 12 | Sara García Alonso | Pedro Duque | Biología / Astronáutica |
| 13 | Silvia Nair Goyanes | Juan Martín Maldacena | Física |
| 14 | Noemí Zaritzky | Lino Barañao | Ingeniería química / Bioquímica |
| 15 | Raquel Lía Chan | Esteban Hopp | Biotecnología vegetal |
| 16 | Barbarita Lara | Claudio Gutiérrez | Informática / Comunicaciones |
| 17 | Loreto Valenzuela | Pablo Valenzuela | Biotecnología de enzimas |
| 18 | Lucía Spangenberg | Rafael Radi | Bioinformática / Bioquímica |
| 19 | Fiorella Haim | Miguel Brechner | Innovación educativa digital |
| 20 | María Clara Betancourt | Manuel Elkin Patarroyo | Ing. ambiental / Inmunología |

> Los pares donde algún miembro no tiene entrada en Wikipedia ES son automáticamente excluidos del análisis comparativo.

---

## 🛠️ Comandos Útiles

```bash
# Ver logs de un servicio concreto
docker-compose logs -f nlp-analyzer

# Reiniciar solo un servicio (p.ej. si actualizas el código)
docker-compose up -d --build api-gateway

# Ejecutar análisis por consola (sin dashboard)
curl -X POST http://localhost:8000/analyze/start

# Ver estado del análisis
curl http://localhost:8000/analyze/status | python3 -m json.tool

# Analizar un par concreto (par 3: Nuria Oliver / Mateo Valero)
curl -X POST "http://localhost:8000/analyze/pair/3?run_llm=false"

# Ver resumen estadístico
curl http://localhost:8000/results/summary | python3 -m json.tool

# Acceder a la documentación interactiva de la API (Swagger)
open http://localhost:8000/docs
open http://localhost:8001/docs
open http://localhost:8002/docs
open http://localhost:8003/docs
```

---

## 📝 Créditos

- **Metodología**: Premio Ada Byron · Universidad de Deusto
- **Corpus femenino**: Premiadas Ada Byron (España + Latinoamérica)
- **Marco teórico**: Data Feminism, Feminist HCI, Role Congruity Theory
- **NLP**: spaCy `es_core_news_lg`
- **LLM-as-a-Judge**: Anthropic Claude Sonnet 4
