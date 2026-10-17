<#
Envia o projeto para a VPS e sobe tudo, usando a chave SSH informada.

1) Diagnóstico (só leitura — não altera nada no servidor):
   powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Servidor 187.102.244.199 `
       -Chave "$env:USERPROFILE\.ssh\radar_vps" -Diagnostico

2) Deploy:
   powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Servidor 187.102.244.199 `
       -Chave "$env:USERPROFILE\.ssh\radar_vps" `
       -MapbiomasUrl "https://drive.google.com/uc?id=SEU_ID&export=download"
#>
param(
  [Parameter(Mandatory = $true)][string]$Servidor,
  [string]$Usuario = "root",
  [int]$Porta = 22,
  [string]$Chave = "",
  [string]$Dominio = "",
  [string]$MapbiomasUrl = "",
  [switch]$SemDemo,
  [switch]$Diagnostico
)
$ErrorActionPreference = "Stop"

$alvo = "$Usuario@$Servidor"
# StrictHostKeyChecking=yes: só conecta se o servidor já estiver no known_hosts (nada é aceito às cegas)
$opts = @("-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15")
if ($Chave -ne "") {
  if (-not (Test-Path $Chave)) { throw "Chave SSH não encontrada: $Chave" }
  $opts += @("-i", $Chave, "-o", "IdentitiesOnly=yes")
}
$sshOpts = @("-p", "$Porta") + $opts
$scpOpts = @("-P", "$Porta") + $opts

# ------------------------------------------------------------ diagnóstico
if ($Diagnostico) {
  Write-Host "==> Diagnóstico (somente leitura) em $alvo" -ForegroundColor Green
  $cmd = "hostname; whoami; . /etc/os-release; echo `$PRETTY_NAME; free -m | sed -n 2p; df -h / | tail -1; " +
         "echo '--- portas em escuta:'; ss -tlnH | awk '{print `$4}' | sort -u; " +
         "echo '--- docker:'; (docker ps --format '{{.Names}}  {{.Ports}}' 2>&1 || echo sem-docker); " +
         "echo '--- ufw:'; (ufw status 2>&1 | head -3); echo '--- /opt:'; ls /opt"
  ssh @sshOpts $alvo $cmd
  exit $LASTEXITCODE
}

# ------------------------------------------------------------------ deploy
$raiz = Split-Path $PSScriptRoot -Parent
$pai = Split-Path $raiz -Parent
$nome = Split-Path $raiz -Leaf
$pacote = Join-Path $env:TEMP "territorial-data-pipeline.tgz"
$destino = "/opt/territorial-data-pipeline"

Write-Host "==> Empacotando o projeto (sem .env, caches e relatórios gerados)" -ForegroundColor Green
tar --exclude=".env" --exclude="__pycache__" --exclude=".pytest_cache" --exclude=".git" `
    --exclude="reports/index.html" -czf $pacote -C $pai $nome
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar (o comando 'tar' existe no seu Windows?)" }

Write-Host "==> Enviando para $alvo" -ForegroundColor Green
scp @scpOpts $pacote "${alvo}:/tmp/territorial-data-pipeline.tgz"
if ($LASTEXITCODE -ne 0) { throw "Falha no scp. Confira o IP, o usuário e a chave SSH." }

$sudo = if ($Usuario -eq "root") { "" } else { "sudo " }
$vars = "MAPBIOMAS_URL='$MapbiomasUrl' SITE_DOMAIN='$Dominio' SEED_DEMO='$(if ($SemDemo) {0} else {1})'"
# o sed remove quebras de linha do Windows (CRLF) que quebrariam o script bash
$remoto = "set -e; ${sudo}mkdir -p $destino; ${sudo}tar xzf /tmp/territorial-data-pipeline.tgz -C $destino --strip-components=1; " +
          "${sudo}sed -i 's/\r$//' $destino/scripts/*.sh; ${sudo}env $vars bash $destino/scripts/bootstrap.sh"

Write-Host "==> Executando a instalação no servidor (pode levar alguns minutos)" -ForegroundColor Green
ssh @sshOpts $alvo $remoto
if ($LASTEXITCODE -ne 0) { throw "A instalação no servidor falhou. Veja as mensagens acima." }
