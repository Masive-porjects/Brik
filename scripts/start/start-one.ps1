#Requires -Version 5.1

# Inicia un solo servicio de midiMastering en una ventana de PowerShell separada.
# Guarda el PID en scripts/.pids para poder detenerlo con stop-all.ps1.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("audiomind", "studio")]
    [string]$Name
)

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$scriptsDir = Split-Path -Parent $PSScriptRoot
$pidsFile = Join-Path $scriptsDir '.pids'
$venvCandidates = @(
    (Join-Path $root 'apps\audiomind\.venv\Scripts\python.exe'),
    (Join-Path $root '.venv\Scripts\python.exe'),
    (Join-Path $root 'apps\audiomind\.venv\bin\python'),
    (Join-Path $root '.venv\bin\python')
)
$pythonExe = $venvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $pythonExe) {
    Write-Error "No se encontro python.exe en apps\audiomind\.venv ni en .venv. Ejecuta primero 'scripts\setup\setup.bat'."
    exit 1
}

$services = @{
    audiomind = @{
        WorkDir = "apps/audiomind"
        Command = "`$env:PYTHONPATH = (Join-Path `$pwd 'src'); & '$pythonExe' -m uvicorn audiomind.main:app --reload --port 8000"
    }
    studio = @{
        WorkDir = "apps/studio"
        Command = "bun run dev"
    }
}

$cfg = $services[$Name]
$wd = Join-Path $root $cfg.WorkDir

Write-Host "Iniciando $Name en $wd"
$process = Start-Process -FilePath "powershell" -WorkingDirectory $wd -PassThru -ArgumentList "-NoExit", "-Command", $cfg.Command
"$Name=$($process.Id)" | Out-File -FilePath $pidsFile -Append
Write-Host "$Name iniciado con PID $($process.Id)."
