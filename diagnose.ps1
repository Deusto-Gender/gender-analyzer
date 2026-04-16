# diagnose.ps1 - WBA v6 nlp-analyzer troubleshooting
# Run from project root: .\diagnose.ps1

param()

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  WBA v6 - Diagnostico de wba-nlp-analyzer" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Verificando Docker Engine..." -ForegroundColor Yellow
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "    ERROR: Docker no esta corriendo." -ForegroundColor Red
    exit 1
}
Write-Host "    OK - Docker Engine activo" -ForegroundColor Green

Write-Host ""
Write-Host "[2] Verificando RAM asignada a Docker..." -ForegroundColor Yellow
$memRaw = docker info --format "{{.MemTotal}}" 2>$null
if ($memRaw) {
    $memMB = [math]::Round([long]$memRaw / 1MB)
    Write-Host "    RAM visible por Docker: $memMB MB" -ForegroundColor White
    if ($memMB -lt 3000) {
        Write-Host "    PROBLEMA: menos de 3 GB de RAM." -ForegroundColor Red
        Write-Host "    SOLUCION: Docker Desktop > Settings > Resources > Memory > 4096 MB" -ForegroundColor Green
    } else {
        Write-Host "    OK - RAM suficiente ($memMB MB)" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "[3] Ultimos logs de wba-nlp-analyzer..." -ForegroundColor Yellow
$exists = docker ps -a --filter "name=wba-nlp-analyzer" --format "{{.Names}}" 2>$null
if ($exists) {
    docker logs wba-nlp-analyzer --tail 30 2>&1
} else {
    Write-Host "    Contenedor no encontrado. Ejecuta primero: docker compose up --build" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "[4] Construyendo nlp-analyzer de forma aislada..." -ForegroundColor Yellow
Write-Host "    (Puede tardar varios minutos - descarga spaCy ~570MB)" -ForegroundColor DarkGray
Write-Host ""

docker build ./services/nlp-analyzer --tag wba-nlp-test --progress plain 2>&1
$buildOk = ($LASTEXITCODE -eq 0)

if ($buildOk) {
    Write-Host "    Build exitoso. Probando carga del modelo..." -ForegroundColor Green
    docker run --rm wba-nlp-test python -c "import spacy; m=spacy.load('es_core_news_sm'); print('OK:', m.meta['name'])" 2>&1
    docker rmi wba-nlp-test -f 2>$null | Out-Null
} else {
    Write-Host "    Build FALLIDO. Causas frecuentes:" -ForegroundColor Red
    Write-Host "    a) Sin conexion a internet (el modelo se descarga de GitHub ~570MB)" -ForegroundColor Yellow
    Write-Host "    b) GitHub rate limiting - espera unos minutos y reintenta" -ForegroundColor Yellow
    Write-Host "    c) Poca RAM durante el build - sube a 4 GB en Docker Desktop" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Si el build va bien pero el contenedor sale (exit 0):" -ForegroundColor White
Write-Host "  Docker Desktop > Settings > Resources > Memory > 4096 MB" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
