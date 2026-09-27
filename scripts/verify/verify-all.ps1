#Requires -Version 5.1

# Verifica que los servicios de midiMastering esten realmente levantados.
# Usa health checks HTTP, conexion TCP a WebSocket y PIDs guardados.

$scriptsDir = Split-Path -Parent $PSScriptRoot
$pidsFile = Join-Path $scriptsDir '.pids'

function Test-HealthEndpoint {
    param([string]$Url, [int]$TimeoutSeconds = 2)
    try {
        $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSeconds -UseBasicParsing -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-TcpPort {
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 2000)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.ConnectAsync($TargetHost, $Port)
        if ($connect.Wait($TimeoutMs)) {
            return $client.Connected
        }
        return $false
    } catch {
        return $false
    }
}

function Get-PidFor {
    param([string]$Name)
    if (-not (Test-Path $pidsFile)) { return $null }
    $line = Get-Content $pidsFile | Where-Object { $_ -like "$Name=*" } | Select-Object -First 1
    if (-not $line) { return $null }
    $parts = $line -split '=', 2
    return $parts[1]
}

function Test-ProcessAlive {
    param([string]$Name)
    $id = Get-PidFor $Name
    if (-not $id) { return $false }
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    return ($null -ne $proc)
}

function Wait-ForService {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [int]$MaxAttempts = 15,
        [int]$DelaySeconds = 1
    )
    Write-Host "Verificando $Name... " -NoNewline
    $ok = $false
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        if (& $Test) {
            $ok = $true
            break
        }
        Start-Sleep -Seconds $DelaySeconds
    }
    if ($ok) {
        Write-Host "OK" -ForegroundColor Green
    } else {
        Write-Host "FALLA" -ForegroundColor Red
    }
    return $ok
}

$results = @()
$results += Wait-ForService "audiomind" { Test-HealthEndpoint "http://localhost:8000/health" } 30 1
$results += Wait-ForService "studio" { Test-HealthEndpoint "http://localhost:3000" } 20 1

if ($results -contains $false) {
    Write-Host "`nAlgunos servicios no responden. Revisa las ventanas de PowerShell." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nTodos los servicios estan activos." -ForegroundColor Green
    exit 0
}
