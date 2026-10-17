<#
Roda o pipeline NO WINDOWS, sem Docker, sem WSL, sem Airflow e sem banco.
Cria um ambiente Python na pasta do projeto (.venv), instala o necessario e executa.

Exemplos (na pasta do projeto):
  powershell -ExecutionPolicy Bypass -File .\scripts\rodar_local.ps1 -MapbiomasUrl "https://drive.google.com/uc?id=SEU_ID&export=download"
  powershell -ExecutionPolicy Bypass -File .\scripts\rodar_local.ps1 -MapbiomasUrl "..." -ForcarFalha     # demonstra o bloqueio por validacao
  powershell -ExecutionPolicy Bypass -File .\scripts\rodar_local.ps1 -MapbiomasUrl "..." -Recarregar      # reprocessa mesmo sem mudanca
#>
param(
  [string]$MapbiomasUrl = $env:MAPBIOMAS_URL,
  [string]$Uf = "PA",
  [string]$Saida = "saida",
  [switch]$ForcarFalha,
  [switch]$Recarregar
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz

if (-not $MapbiomasUrl) { throw "Informe o link do MapBiomas: -MapbiomasUrl 'https://drive.google.com/uc?id=...&export=download'" }

$py = $null
foreach ($c in @("py", "python")) { if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break } }
if (-not $py) { throw "Python nao encontrado. Instale em python.org (marque 'Add python.exe to PATH')." }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "==> Criando ambiente Python (.venv)" -ForegroundColor Green
  if ($py -eq "py") { & py -3 -m venv .venv } else { & python -m venv .venv }
}
$venvPy = Join-Path $raiz ".venv\Scripts\python.exe"

Write-Host "==> Instalando dependencias (so na primeira vez)" -ForegroundColor Green
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements-local.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias." }

$env:PYTHONPATH = Join-Path $raiz "src"
$args = @("-m", "territorial.local_run", "--uf", $Uf, "--saida", $Saida, "--mapbiomas-url", $MapbiomasUrl)
if ($ForcarFalha) { $args += "--forcar-falha-validacao" }
if ($Recarregar) { $args += @("--ignorar-checksum") }

Write-Host "==> Executando o pipeline" -ForegroundColor Green
& $venvPy @args
$codigo = $LASTEXITCODE
if ($codigo -eq 0) {
  $rel = Join-Path $raiz "$Saida\relatorio\index.html"
  if (Test-Path $rel) { Write-Host "==> Abrindo o relatorio no navegador" -ForegroundColor Green; Start-Process $rel }
}
exit $codigo
