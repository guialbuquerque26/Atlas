# ============================================================
#  Atlas — sobe TODOS os serviços de uma vez
#  Uso:  .\scripts\iniciar.ps1
#        .\scripts\iniciar.ps1 -BaixarModelos
# ============================================================
param(
    [switch]$BaixarModelos,
    [switch]$SemNavegador,
    [string[]]$Servicos = @()
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-Not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Ambiente virtual ausente. Rode primeiro:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1`n"
    exit 1
}

if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env criado a partir do exemplo." -ForegroundColor Cyan
}

$argumentos = @("-m", "atlas.supervisor", "iniciar") + $Servicos
if ($BaixarModelos) { $argumentos += "--baixar-modelos" }
if ($SemNavegador)  { $argumentos += "--sem-navegador" }

& .\.venv\Scripts\python.exe @argumentos
exit $LASTEXITCODE
