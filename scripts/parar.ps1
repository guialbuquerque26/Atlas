# ============================================================
#  Atlas — derruba os serviços iniciados pelo Atlas
#  Uso:  .\scripts\parar.ps1
#        .\scripts\parar.ps1 -Tudo    (inclui o Ollama adotado)
# ============================================================
param(
    [switch]$Tudo,
    [string[]]$Servicos = @()
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$argumentos = @("-m", "atlas.supervisor", "parar") + $Servicos
if ($Tudo) { $argumentos += "--tudo" }

& .\.venv\Scripts\python.exe @argumentos
exit $LASTEXITCODE
