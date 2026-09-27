#Requires -Version 5.1

# Setup completo del entorno local de WaveAI - IDEMPOTENTE:
# cada paso se salta si ya esta hecho, se puede correr mil veces.
# Equivale a docs/runbooks/SETUP.md pero en un solo script (Windows).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# El venv vive en apps\audiomind\.venv (convención de start-one.ps1 y del
# entorno real): los start scripts lanzan uvicorn desde apps/audiomind.
$venvDir = Join-Path $root 'apps\audiomind\.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$fail = $false

function Step-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Step-Info { param($msg) Write-Host "  [..] $msg" -ForegroundColor Cyan }
function Step-Fail { param($msg) Write-Host "  [XX] $msg" -ForegroundColor Red; $script:fail = $true }

Write-Host "== 1/5 Python + .venv ==" -ForegroundColor White
if (Test-Path $venvPython) {
    Step-Ok ".venv ya existe"
} else {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Step-Info "creando .venv con 'py -3.12'"
        & py -3.12 -m venv $venvDir
    } else {
        Step-Info "creando .venv con 'python'"
        & python -m venv $venvDir
    }
    if (Test-Path $venvPython) { Step-Ok ".venv creado" }
    else { Step-Fail "no se pudo crear .venv - instala Python 3.12 (python.org)" }
}

Write-Host "== 2/5 dependencias Python ==" -ForegroundColor White
if (Test-Path $venvPython) {
    & $venvPython -c "import uvicorn, fastapi, audiomind" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Step-Ok "deps Python ya instaladas"
    } else {
        # AudioMind va editable (src-layout): -e apps/audiomind instala TODAS
        # las deps del proyecto (fastapi, uvicorn, librosa, pedalboard...).
        # apps\bridge y simulator fueron removidos del producto (2026-09-11):
        # sus requirements.txt ya NO existen, no se instalan.
        Step-Info "instalando audiomind editable (tarda varios min la primera vez)"
        & $venvPython -m pip install --retries 15 --timeout 90 `
            -e (Join-Path $root 'apps\audiomind')
        & $venvPython -c "import uvicorn, fastapi, audiomind" 2>$null
        if ($LASTEXITCODE -eq 0) { Step-Ok "deps Python instaladas" }
        else { Step-Fail "fallo la instalacion de deps Python" }
    }
}

Write-Host "== 3/5 bun ==" -ForegroundColor White
if (Get-Command bun -ErrorAction SilentlyContinue) {
    Step-Ok "bun disponible ($(& bun --version))"
} else {
    Step-Info "instalando bun (bun.sh/install.ps1)"
    try {
        & powershell -NoProfile -Command "irm bun.sh/install.ps1 | iex"
        $env:Path = "$env:USERPROFILE\.bun\bin;$env:Path"
    } catch {}
    if (Get-Command bun -ErrorAction SilentlyContinue) { Step-Ok "bun instalado" }
    else { Step-Fail "bun no disponible - instala manual: https://bun.sh" }
}

Write-Host "== 4/5 node_modules (bun install) ==" -ForegroundColor White
if (Test-Path (Join-Path $root 'node_modules')) {
    Step-Ok "node_modules ya existe"
} elseif (Get-Command bun -ErrorAction SilentlyContinue) {
    Step-Info "bun install en la raiz"
    Push-Location $root
    & bun install
    Pop-Location
    if (Test-Path (Join-Path $root 'node_modules')) { Step-Ok "node_modules instalado" }
    else { Step-Fail "bun install no genero node_modules" }
} else {
    Step-Fail "sin bun no se puede instalar node_modules"
}

Write-Host "== 5/5 apps/agent dist + .env.local ==" -ForegroundColor White
$agentDist = Join-Path $root 'apps\agent\dist\index.js'
if (Test-Path $agentDist) {
    Step-Ok "apps/agent/dist ya existe"
} elseif (Get-Command bun -ErrorAction SilentlyContinue) {
    # @midimastering/agent apunta a dist/ - sin build el studio falla con TS2307
    Step-Info "build de @midimastering/agent"
    Push-Location (Join-Path $root 'apps\agent')
    & bun run build
    Pop-Location
    if (Test-Path $agentDist) { Step-Ok "agent compilado" }
    else { Step-Fail "build del agent no genero dist/" }
} else {
    Step-Fail "sin bun no se puede compilar apps/agent"
}

$envLocal = Join-Path $root 'apps\studio\.env.local'
$envExample = Join-Path $root 'apps\studio\.env.local.example'
if (Test-Path $envLocal) {
    Step-Ok ".env.local ya existe"
} elseif (Test-Path $envExample) {
    Copy-Item $envExample $envLocal
    Step-Ok ".env.local creado desde .env.local.example"
    Step-Info "Convex es opcional: NEXT_PUBLIC_CONVEX_URL queda vacia (la app corre sin auth)"
}

Write-Host ""
if ($fail) {
    Write-Host "Setup termino con errores - revisa los [XX] de arriba." -ForegroundColor Red
    exit 1
}
Write-Host "Setup completo. Ya puedes correr scripts\start\start-all.bat" -ForegroundColor Green
exit 0
