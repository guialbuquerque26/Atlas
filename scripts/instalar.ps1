# ============================================================
#  Atlas — instalação no Windows
#  Uso:  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#        ... -SemModelos     (pula o download dos modelos)
# ============================================================
param([switch]$SemModelos)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = ".\.venv\Scripts\python.exe"

Write-Host "`n[1/6] Verificando o Python..." -ForegroundColor Cyan
$versao = (python --version) 2>&1
if ($LASTEXITCODE -ne 0) { throw "Python nao encontrado no PATH. Instale o Python 3.11 ou superior." }
Write-Host "      $versao"

Write-Host "`n[2/6] Criando o ambiente virtual..." -ForegroundColor Cyan
if (-Not (Test-Path $py)) { python -m venv .venv; Write-Host "      .venv criado." }
else { Write-Host "      .venv ja existe." }

Write-Host "`n[3/6] Instalando as dependencias..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias." }
# Modo editavel: torna o pacote "atlas" importavel de qualquer diretorio.
& $py -m pip install -e . --no-deps --quiet
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar o pacote atlas." }

Write-Host "`n[4/6] Preparando o arquivo .env..." -ForegroundColor Cyan
if (-Not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "      .env criado a partir do exemplo." }
else { Write-Host "      .env ja existe, mantido como esta." }

Write-Host "`n[5/6] Baixando os modelos no Ollama..." -ForegroundColor Cyan
if ($SemModelos) {
    Write-Host "      pulado (-SemModelos)."
} elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
    ollama pull qwen2.5:7b-instruct
    ollama pull qwen2.5vl:7b
    ollama pull nomic-embed-text
} else {
    Write-Host "      Ollama nao encontrado. Instale em https://ollama.com/download" -ForegroundColor Yellow
    Write-Host "      Depois rode:  .\scripts\iniciar.ps1 -BaixarModelos"
}

Write-Host "`n[6/6] Rodando os testes de fundacao..." -ForegroundColor Cyan
& $py -m pytest testes -q

Write-Host "`nPronto." -ForegroundColor Green
Write-Host "  Subir tudo de uma vez ...  .\scripts\iniciar.ps1"
Write-Host "  Ver o estado ............   .\scripts\status.ps1"
Write-Host "  Derrubar tudo ...........   .\scripts\parar.ps1`n"
