param(
    [int]$ApiPort = 8001,
    [int]$WebPort = 8501,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $env:LOCALAPPDATA "miniproject-tools"
$minGit = Join-Path $tools "MinGit\cmd"
$ollama = Join-Path $tools "ollama"

if (Test-Path $ollama) { $env:PATH = "$ollama;$env:PATH" }
if (Test-Path $minGit) { $env:PATH = "$minGit;$env:PATH" }
$env:GIT_PYTHON_GIT_EXECUTABLE = Join-Path $minGit "git.exe"
$env:PYTHONPATH = $root

if (-not $FrontendOnly) {
    $ollamaUp = $false
    try { if (curl.exe -s -m 3 http://127.0.0.1:11434/api/tags) { $ollamaUp = $true } } catch {}
    if (-not $ollamaUp) {
        Start-Process -FilePath (Join-Path $ollama "ollama.exe") -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
    Write-Host "Backend  : http://127.0.0.1:$ApiPort  (docs at /docs)"
    Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort" -WorkingDirectory $root -WindowStyle Normal
}

if (-not $BackendOnly) {
    Start-Sleep -Seconds 3
    Write-Host "Frontend : http://127.0.0.1:$WebPort"
    $env:BACKEND_URL = "http://127.0.0.1:$ApiPort"
    Start-Process -FilePath "python" -ArgumentList "-m", "streamlit", "run", "frontend\app.py", "--server.port", "$WebPort", "--server.headless", "true" -WorkingDirectory $root -WindowStyle Normal
}

Write-Host "Press Ctrl+C in this window to stop. Close the opened server windows to shut everything down."
Read-Host "Press Enter to exit this launcher"
