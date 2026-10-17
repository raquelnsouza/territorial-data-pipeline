#!/usr/bin/env bash
# Prepara o servidor (Ubuntu) e sobe o projeto. Roda NO servidor, como root.
#
# Variáveis opcionais:
#   MAPBIOMAS_URL   link do .xlsx no Google Drive (compartilhado: "Qualquer pessoa com o link")
#   SITE_DOMAIN     domínio apontado para o servidor (padrão: IP-com-hifens.sslip.io)
#   SEED_DEMO=0     não dispara a sequência de demonstração
#   PREPARAR_APENAS=1   só gera o .env e para (útil para testar)
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------- .env
definir() {  # definir CHAVE VALOR  → grava/atualiza no .env sem mexer nas outras linhas
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  { grep -v "^${k}=" .env 2>/dev/null || true; printf '%s=%s\n' "$k" "$v"; } > "$tmp"
  cat "$tmp" > .env; rm -f "$tmp"
}
obter() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }
aleatorio() { openssl rand -hex 16; }

preparar_env() {
  if [ ! -f .env ]; then
    log "Gerando .env com senhas e chaves aleatórias"
    cp .env.example .env
    definir AIRFLOW_DB_PASSWORD "$(aleatorio)"
    definir POSTGIS_PASSWORD "$(aleatorio)"
    definir AIRFLOW_ADMIN_PASSWORD "$(aleatorio)"
    definir AIRFLOW_VIEWER_PASSWORD "$(aleatorio)"
    definir AIRFLOW_FERNET_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"   # formato Fernet (base64 url-safe de 32 bytes)
    definir AIRFLOW_SECRET_KEY "$(openssl rand -hex 32)"
  else
    log "Mantendo o .env existente (senhas já geradas)"
  fi
  chmod 600 .env

  if [ -n "${MAPBIOMAS_URL:-}" ]; then definir MAPBIOMAS_URL "$MAPBIOMAS_URL"; fi
  [ -n "$(obter MAPBIOMAS_URL)" ] || aviso "MAPBIOMAS_URL vazio: a coleta do MapBiomas vai falhar até você preencher (docs/MAPBIOMAS_FONTE.md)."

  if [ -n "${SITE_DOMAIN:-}" ]; then
    definir SITE_ADDRESS "$SITE_DOMAIN"
  elif [ "$(obter SITE_ADDRESS)" = "" ] || [ "$(obter SITE_ADDRESS)" = ":80" ]; then
    local ip; ip="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
    definir SITE_ADDRESS "${ip//./-}.sslip.io"
  fi
}

preparar_env
if [ "${PREPARAR_APENAS:-0}" = "1" ]; then log ".env pronto (modo PREPARAR_APENAS)"; exit 0; fi

[ "$(id -u)" -eq 0 ] || erro "Rode como root (ou com sudo)."

# ------------------------------------------------------------- recursos
ram_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
if [ "$ram_mb" -lt 3500 ] && [ "${FORCAR:-0}" != "1" ]; then
  erro "Só ${ram_mb} MB de RAM: o Airflow precisa de ~4 GB. Aumente a VPS ou use FORCAR=1 por sua conta e risco."
fi
disco_gb="$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
[ "$disco_gb" -ge 10 ] || aviso "Pouco disco livre (${disco_gb} GB)."

# --------------------------------------------------------------- docker
if ! command -v docker >/dev/null 2>&1; then
  log "Instalando o Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || erro "Docker Compose (plugin) não encontrado."

# ----------------------------------------------- servidor já em uso?
# Se outra coisa já usa as portas 80/443 (outro site, proxy...), não mexemos: avisamos e paramos.
porta_ocupada() {  # usa ss (padrão no Ubuntu); sem ele, tenta conectar na porta local
  if command -v ss >/dev/null 2>&1; then
    ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}
if docker compose ps --status running -q 2>/dev/null | grep -q .; then
  log "Este projeto já está rodando aqui; vamos apenas atualizá-lo"
else
  for p in 80 443; do
    if porta_ocupada "$p"; then
      erro "A porta $p já está em uso neste servidor (veja: ss -tlnp | grep :$p). Para não derrubar o que já roda, parei aqui.
       Opções: liberar a porta, ou colocar este projeto atrás do proxy que já existe (me peça o ajuste)."
    fi
  done
fi

# ------------------------------------------------------------- firewall
# Só adiciona regras se o ufw JÁ estiver ativo. Não ativamos firewall em servidor alheio (risco de se trancar fora).
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  log "ufw ativo: liberando 80 e 443 (as regras existentes são mantidas)"
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
else
  aviso "ufw inativo: não alterei o firewall. Se quiser, ative-o liberando antes a porta do SSH."
fi

# ------------------------------------------------------------------ subir
log "Construindo e subindo os serviços (a primeira vez demora alguns minutos)"
docker compose up -d --build

log "Aguardando o Airflow ficar saudável"
for i in $(seq 1 60); do
  if docker compose exec -T airflow-webserver curl -fs http://localhost:8080/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
[ "${ok:-0}" = "1" ] || { docker compose ps; erro "O Airflow não ficou saudável em 5 min. Veja: docker compose logs airflow-webserver"; }

log "Aguardando o DAG ser carregado"
for i in $(seq 1 36); do
  if docker compose exec -T airflow-scheduler airflow dags list 2>/dev/null | grep -q territorial_update; then dag=1; break; fi
  sleep 5
done
[ "${dag:-0}" = "1" ] || aviso "O DAG ainda não apareceu; dispare manualmente no Airflow."

# ----------------------------------------------------- demonstração
if [ "${dag:-0}" = "1" ] && [ "${SEED_DEMO:-1}" = "1" ] && [ -n "$(obter MAPBIOMAS_URL)" ]; then
  log "Disparando a sequência de demonstração (carga, falha simulada, execução sem mudança)"
  af() { docker compose exec -T airflow-scheduler airflow "$@"; }
  af dags trigger territorial_update >/dev/null
  sleep 3
  af dags trigger territorial_update -c '{"forcar_falha_validacao": true, "ignorar_checksum": true}' >/dev/null
  sleep 3
  af dags trigger territorial_update >/dev/null
fi

# ---------------------------------------------------------------- resumo
site="$(obter SITE_ADDRESS)"
case "$site" in :*) base="http://$(hostname -I | awk '{print $1}')${site}" ;; *) base="https://${site}" ;; esac
cat <<RESUMO

════════════════════════════════════════════════════════════
 Pronto! (a primeira emissão do certificado HTTPS leva ~1 min)

 Airflow:    ${base}/
 Relatório:  ${base}/relatorio/   (aparece depois da 1ª carga)

 Usuário admin     : admin      senha: $(obter AIRFLOW_ADMIN_PASSWORD)
 Usuário visitante : visitante  senha: $(obter AIRFLOW_VIEWER_PASSWORD)   (somente leitura)

 Senhas guardadas em: ${RAIZ}/.env (permissão 600)
 Acompanhar: cd ${RAIZ} && docker compose logs -f airflow-scheduler
════════════════════════════════════════════════════════════
RESUMO
