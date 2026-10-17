#!/usr/bin/env bash
# Sobe o Airflow (sem Docker) no WSL/Linux, usando a DAG file-based (sem PostGIS).
# Uso:  source ~/af/bin/activate && bash scripts/airflow_wsl.sh
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export AIRFLOW_HOME="${AIRFLOW_HOME:-$HOME/airflow_territorial}"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJ/dags_local"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DAG_DISCOVERY_SAFE_MODE=False
export PYTHONPATH="$PROJ/src${PYTHONPATH:+:$PYTHONPATH}"
export TERRITORIAL_SAIDA="${TERRITORIAL_SAIDA:-$HOME/territorial_saida}"
export TERRITORIAL_DATA_DIR="${TERRITORIAL_DATA_DIR:-$HOME/territorial_dados}"
export AIRFLOW_VAR_MAPBIOMAS_URL="${AIRFLOW_VAR_MAPBIOMAS_URL:-https://drive.google.com/uc?id=1otOqymHuixvkRGVl65zTTNyfaHo46Gqk&export=download}"

mkdir -p "$TERRITORIAL_SAIDA" "$TERRITORIAL_DATA_DIR"
command -v airflow >/dev/null || { echo "airflow nao encontrado: ative o venv (source ~/af/bin/activate)"; exit 1; }

echo "Airflow em http://localhost:8080  (usuario: admin; senha em $AIRFLOW_HOME/simple_auth_manager_passwords.json.generated ou impressa abaixo)"
echo "Saidas: $TERRITORIAL_SAIDA  (no Windows: explorer.exe \$(wslpath -w $TERRITORIAL_SAIDA))"
exec airflow standalone
