# Sobe SOMENTE a interface web do Atlas, em primeiro plano (Ctrl+C encerra).
# Para subir tudo de uma vez, use .\scripts\iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m atlas.ui.app
