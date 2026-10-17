"""Gera a página-resumo (HTML estático) com mapa, últimas atualizações e validações.

Duas entradas, mesma página:
* ``gerar(engine, uf)``: lê tudo do PostGIS (uso no Airflow);
* ``renderizar(...)``: recebe DataFrames prontos (uso no modo local, sem banco).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config
from .transform import resumo_por_municipio


def _tabela(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "<p>Sem registros.</p>"
    cab = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    linhas = "".join(
        "<tr>" + "".join(f"<td>{html.escape('' if pd.isna(v) else str(v))}</td>" for v in row) + "</tr>"
        for row in df.itertuples(index=False)
    )
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{linhas}</tbody></table>"


def renderizar(mun: gpd.GeoDataFrame, cob: pd.DataFrame, ultimas: pd.DataFrame, validacoes: pd.DataFrame,
               uf: str, destino: Path) -> Path:
    """Monta o HTML. ``mun``: cd_mun, nm_mun, geometry. ``cob``: cd_mun, ano, classe_id, area_ha."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    mun = mun[["cd_mun", "nm_mun", "geometry"]].copy()
    ano = None
    if not cob.empty:
        resumo = resumo_por_municipio(mun, cob, config.CLASSE_FLORESTA_ID)
        mun = mun.merge(resumo[["cd_mun", "pct_classe"]], on="cd_mun", how="left")
        mun["pct_classe"] = mun["pct_classe"].round(1)
        ano = int(cob["ano"].max())
    else:
        mun["pct_classe"] = None

    geojson = json.loads(mun[["cd_mun", "nm_mun", "pct_classe", "geometry"]].to_json())
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atualização automatizada de bases territoriais — demonstração</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 body{{font-family:system-ui,sans-serif;margin:0;color:#1f2933;background:#f7f8f5}}
 header{{background:#14532d;color:#fff;padding:20px 5vw}} h1{{margin:0;font-size:1.3rem}}
 header p{{margin:.3rem 0 0;opacity:.85;font-size:.9rem}}
 main{{padding:16px 5vw 40px;max-width:1200px;margin:auto}}
 #mapa{{height:460px;border-radius:8px;border:1px solid #d5dbd0}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem;background:#fff}}
 th,td{{border:1px solid #e1e5dc;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#eef2ea}} .box{{overflow-x:auto}} h2{{font-size:1.05rem;margin-top:28px}}
</style></head><body>
<header><h1>Atualização automatizada de bases territoriais ({html.escape(uf)})</h1>
<p>Demonstração técnica — IBGE (malha municipal) + MapBiomas (cobertura do solo). Gerado em {agora}.</p></header>
<main>
<h2>Formação florestal por município{f" — {ano}" if ano else ""} (% da área)</h2>
<div id="mapa"></div>
<h2>Validações da última execução</h2><div class="box">{_tabela(validacoes)}</div>
<h2>Histórico de atualizações (rastreabilidade)</h2><div class="box">{_tabela(ultimas)}</div>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const dados = {json.dumps(geojson)};
const mapa = L.map('mapa'); 
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap'}}).addTo(mapa);
const cor = v => v==null ? '#cccccc' : v>90 ? '#14532d' : v>75 ? '#2f855a' : v>50 ? '#68b684' : v>25 ? '#b7dfb9' : '#f1f7e4';
const camada = L.geoJSON(dados, {{
  style: f => ({{fillColor: cor(f.properties.pct_classe), weight: .6, color: '#555', fillOpacity: .85}}),
  onEachFeature: (f, l) => l.bindTooltip(f.properties.nm_mun + ': ' + (f.properties.pct_classe ?? 'sem dado') + '%')
}}).addTo(mapa);
mapa.fitBounds(camada.getBounds());
</script></body></html>"""
    destino.write_text(pagina, encoding="utf-8")
    return destino


def gerar(engine, uf: str, destino: Path | None = None) -> Path:
    """Lê do PostGIS e gera a página (usado pelo DAG)."""
    from sqlalchemy import text  # import tardio: o modo local não precisa de SQLAlchemy

    destino = destino or (config.REPORT_DIR / "index.html")
    mun = gpd.read_postgis(
        "SELECT cd_mun, nm_mun, uf, area_ha_ibge, geometry FROM territorial.municipios WHERE uf = %(uf)s",
        engine, geom_col="geometry", params={"uf": uf},
    )
    cob = pd.read_sql(
        text("SELECT cd_mun, ano, classe_id, area_ha FROM territorial.cobertura_mapbiomas WHERE cd_mun LIKE :p"),
        engine, params={"p": f"{config.ESTADOS[uf].codigo_ibge}%"},
    )
    ult = pd.read_sql(
        text("SELECT criado_em::timestamp(0) AS quando, base, status, linhas, left(sha256, 12) AS sha256, detalhe "
             "FROM audit.atualizacoes ORDER BY criado_em DESC LIMIT 12"),
        engine,
    )
    run_ok = pd.read_sql(text("SELECT run_id FROM audit.validacoes ORDER BY criado_em DESC LIMIT 1"), engine)
    val = pd.DataFrame()
    if not run_ok.empty:
        val = pd.read_sql(
            text("SELECT regra, status, detalhe FROM audit.validacoes WHERE run_id = :r ORDER BY id"),
            engine, params={"r": run_ok.iloc[0, 0]},
        )
    return renderizar(mun, cob, ult, val, uf, destino)
