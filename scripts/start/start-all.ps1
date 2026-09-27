#Requires -Version 5.1

# Inicia todos los servicios de midiMastering en ventanas de PowerShell separadas.
# Guarda los PIDs en scripts/.pids para poder detenerlos con stop-all.ps1.

$scriptsDir = Split-Path -Parent $PSScriptRoot
$pidsFile = Join-Path $scriptsDir '.pids'

if (Test-Path $pidsFile) {
    Remove-Item $pidsFile -Force
}

Write-Host ">>> [1/2] Iniciando backend (audiomind)..." -ForegroundColor Cyan
& "$PSScriptRoot\start-one.ps1" -Name "audiomind"

# Esperar activamente a que audiomind este respondiendo antes de iniciar el frontend
$verifyScript = Join-Path (Split-Path -Parent $PSScriptRoot) "verify\verify-all.ps1"
$audiomindReady = $false
$maxAttempts = 30
$delaySeconds = 1

Write-Host "Esperando a que audiomind este online (http://localhost:8000/health)... " -NoNewline
for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $audiomindReady = $true
            break
        }
    } catch {
        # Esperando inicio del servidor
    }
    Start-Sleep -Seconds $delaySeconds
}

if ($audiomindReady) {
    Write-Host "OK (online)" -ForegroundColor Green
} else {
    Write-Host "ADVERTENCIA: audiomind tardo mas de lo previsto en responder." -ForegroundColor Yellow
}

Write-Host "`n>>> [2/2] Iniciando frontend (studio)..." -ForegroundColor Cyan
& "$PSScriptRoot\start-one.ps1" -Name "studio"

Write-Host "`nServicios iniciados. PIDs guardados en $pidsFile"
Write-Host "Verificando estado final de todos los servicios..." -ForegroundColor Cyan

& "$PSScriptRoot\..\verify\verify-all.ps1"
