"""
Frontend Service v6
Serves:
  - GET /            → Jinja2 template (templates/dashboard.html)
  - /static/*        → Static files (CSS + JS)
No inline HTML or JavaScript in this Python file.
"""
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Wikipedia Bias Analyzer Frontend v6")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "http://localhost:8000")


APP_VERSION = "6.2.0"  # bump to bust browser cache

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "api_gateway_url": API_GATEWAY_URL,
        "app_version": APP_VERSION,
    })


@app.get("/health")
def health():
    return {"status": "ok", "service": "frontend", "version": "6.0.0"}
