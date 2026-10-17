#!/usr/bin/env bash
# Sobe o projeto dentro do GitHub Codespaces (sem instalar nada no seu computador).
# Roda sozinho na criação do Codespace; pode ser repetido à vontade.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# .env com senhas aleatórias (o bootstrap.sh já sabe gerar); sem domínio, porta 8080
SITE_DOMAIN=":80" PREPARAR_APENAS=1 bash scripts/bootstrap.sh
if grep -q '^HTTP_PORT=' .env; then sed -i 's/^HTTP_PORT=.*/HTTP_PORT=8080/' .env; else echo 'HTTP_PORT=8080' >> .env; fi

if [ -z "$(grep -E '^MAPBIOMAS_URL=' .env | cut -d= -f2-)" ]; then
  echo ""
  echo "ATENÇÃO: defina o link do MapBiomas (Drive) em um destes lugares e rode de novo:"
  echo "  - Codespaces secret MAPBIOMAS_URL (GitHub > Settings > Codespaces > Secrets), ou"
  echo "  - edite MAPBIOMAS_URL no arquivo .env"
fi
if [ -n "${MAPBIOMAS_URL:-}" ]; then sed -i "s#^MAPBIOMAS_URL=.*#MAPBIOMAS_URL=${MAPBIOMAS_URL}#" .env; fi

docker compose up -d --build
echo ""
echo "Airflow subindo. Abra a aba PORTAS e clique no endereço da porta 8080."
echo "Usuário: admin   Senha: $(grep '^AIRFLOW_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
