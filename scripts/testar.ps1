# Roda os testes de fundacao (nao exigem Ollama nem internet)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m pytest testes -v
exit $LASTEXITCODE
