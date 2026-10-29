# ============================================================
#  Atlas — estado de cada serviço e dos modelos
#  Uso:  .\scripts\status.ps1
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

& .\.venv\Scripts\python.exe -m atlas.supervisor status
& .\.venv\Scripts\python.exe -m atlas.cli doutor
exit $LASTEXITCODE
