param(
    [string]$Model = "qwen2.5:1.5b",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$tools = Join-Path $env:LOCALAPPDATA "miniproject-tools"
$minGitDir = Join-Path $tools "MinGit"
$ollamaDir = Join-Path $tools "ollama"
New-Item -ItemType Directory -Force -Path $tools | Out-Null

function Get-File($Url, $Destination) {
    if ((Test-Path $Destination) -and -not $Force) {
        Write-Host "Already downloaded: $Destination"
        return
    }
    Write-Host "Downloading $Url"
    curl.exe -L --retry 3 -o $Destination $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
}

if (-not (Test-Path (Join-Path $minGitDir "cmd\git.exe"))) {
    $mingitZip = Join-Path $tools "MinGit-64.zip"
    Get-File "https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.1/MinGit-2.56.0-64-bit.zip" $mingitZip
    New-Item -ItemType Directory -Force -Path $minGitDir | Out-Null
    tar -xf $mingitZip -C $minGitDir
    Write-Host "Portable Git installed at $minGitDir"
}

$gitVersion = & (Join-Path $minGitDir "cmd\git.exe") --version
Write-Host $gitVersion

if (-not (Test-Path (Join-Path $ollamaDir "ollama.exe"))) {
    $ollamaZip = Join-Path $tools "ollama-windows-amd64.zip"
    Get-File "https://github.com/ollama/ollama/releases/download/v0.35.0/ollama-windows-amd64.zip" $ollamaZip
    New-Item -ItemType Directory -Force -Path $ollamaDir | Out-Null
    tar -xf $ollamaZip -C $ollamaDir
    Write-Host "Ollama installed at $ollamaDir"
}

$env:PATH = "$ollamaDir;$minGitDir\cmd;$env:PATH"

$ollamaUp = $false
try {
    $tags = curl.exe -s -m 5 http://127.0.0.1:11434/api/tags
    if ($tags) { $ollamaUp = $true }
} catch { $ollamaUp = $false }

if (-not $ollamaUp) {
    Write-Host "Starting ollama serve..."
    Start-Process -FilePath (Join-Path $ollamaDir "ollama.exe") -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 6
}

curl.exe -s -m 5 http://127.0.0.1:11434/api/tags | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Ollama server did not start on 127.0.0.1:11434" }

$installed = (curl.exe -s -m 5 http://127.0.0.1:11434/api/tags | ConvertFrom-Json).models.name
if ($installed -notcontains $Model) {
    Write-Host "Pulling model $Model ..."
    & (Join-Path $ollamaDir "ollama.exe") pull $Model
}

Write-Host "Setup complete. Models: $((curl.exe -s -m 5 http://127.0.0.1:11434/api/tags | ConvertFrom-Json).models.name -join ', ')"
