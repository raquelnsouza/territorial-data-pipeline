"""Teste ponta a ponta LOCAL: sobe um servidor falso das fontes e executa o DAG inteiro.

Uso (precisa de Airflow + PostGIS locais; veja README, seção "Testes"):
    python tests/e2e_local.py
Não faz parte do pytest porque exige Airflow instalado e banco real.
"""
import http.server
import json
import os
import sys
import threading
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

RAIZ = Path(__file__).resolve().parent.parent
PASTA = Path(os.environ.get("E2E_DIR", "/tmp/e2e"))
PASTA.mkdir(parents=True, exist_ok=True)

# ---------- dados falsos, no mesmo formato das fontes reais
linhas = [{"codarea": f"15{i:05d}", "geometry": box(-55 + (i % 12) * .1, -3 + (i // 12) * .1, -54.9 + (i % 12) * .1, -2.9 + (i // 12) * .1)} for i in range(144)]
gdf = gpd.GeoDataFrame(linhas, crs="EPSG:4674")
(PASTA / "malha.geojson").write_text(gdf.to_json())
(PASTA / "locs.json").write_text(json.dumps([{"id": int(f"15{i:05d}"), "nome": f"Municipio {i}"} for i in range(144)]))
area = gdf.to_crs("EPSG:5880").geometry.area / 10_000
rows = []
for i, a in enumerate(area):
    for cid, fr in ((3, .7), (15, .3)):
        r = {"feature_id": i, "biome": "Amazônia", "geocode": f"15{i:05d}", "class_id": cid, "class_level_4": f"c{cid}"}
        r.update({str(y): a * fr for y in range(2020, 2024)})
        rows.append(r)
pd.DataFrame(rows).to_excel(PASTA / "mapbiomas.xlsx", sheet_name=os.environ.get("MAPBIOMAS_ABA", "COVERAGE_10"), index=False)

ROTAS = {"/api/v3/malhas/estados/15": "malha.geojson", "/api/v1/localidades/estados/15/municipios": "locs.json"}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        caminho = self.path.split("?")[0]
        nome = ROTAS.get(caminho) or ("mapbiomas.xlsx" if caminho == "/mapbiomas.xlsx" else None)
        if not nome:
            self.send_error(404)
            return
        dados = (PASTA / nome).read_bytes()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["IBGE_API_BASE"] = "http://127.0.0.1:8765"
os.environ["AIRFLOW_VAR_MAPBIOMAS_URL"] = "http://127.0.0.1:8765/mapbiomas.xlsx"
os.environ["TERRITORIAL_DATA_DIR"] = str(PASTA / "data")
os.environ["TERRITORIAL_REPORT_DIR"] = str(PASTA / "reports")
sys.path.insert(0, str(RAIZ / "src"))

import pendulum  # noqa: E402
from airflow.models import DagBag  # noqa: E402

DAG_ID = os.environ.get("E2E_DAG", "territorial_update")
PASTA_DAGS = os.environ.get("E2E_DAGS", "dags")
dag = DagBag(dag_folder=str(RAIZ / PASTA_DAGS), include_examples=False).dags[DAG_ID]


def rodar(rotulo, **params):
    print(f"\n===== {rotulo} {params} =====", flush=True)
    try:
        run = dag.test(run_conf=params, execution_date=pendulum.now("UTC"))
        print("estado final:", {ti.task_id: ti.state for ti in run.get_task_instances()})
    except Exception as e:  # noqa: BLE001
        print("ERRO propagado:", type(e).__name__, str(e)[:300])


rodar("1) primeira carga")
rodar("2) segunda execução, fontes iguais (deve pular)")
rodar("3) falha simulada de validação", forcar_falha_validacao=True, ignorar_checksum=True)
rodar("4) recarga forçada", ignorar_checksum=True, forcar_falha_validacao=False)  # dag.test() reaproveita params da chamada anterior
srv.shutdown()
