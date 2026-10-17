"""Carga no PostGIS: grava em ``staging`` e troca na tabela final numa única transação.

Se algo falhar no meio, o ``ROLLBACK`` mantém a versão anterior intacta: o usuário da
ferramenta nunca enxerga uma carga pela metade.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config

log = logging.getLogger(__name__)


def _para_multipoligono(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.apply(lambda g: MultiPolygon([g]) if g.geom_type == "Polygon" else g)
    return gdf


def carregar_municipios(engine: Engine, gdf: gpd.GeoDataFrame, run_id: str, uf: str) -> int:
    gdf = _para_multipoligono(gdf)
    gdf["run_id"] = run_id
    with engine.begin() as con:
        con.execute(text("DROP TABLE IF EXISTS staging.municipios"))
        gdf.to_postgis("municipios", con, schema="staging", if_exists="replace", index=False)
        con.execute(text("DELETE FROM territorial.municipios WHERE uf = :uf"), dict(uf=uf))
        con.execute(
            text(
                """
                INSERT INTO territorial.municipios (cd_mun, nm_mun, uf, area_ha_ibge, geometry, run_id)
                SELECT cd_mun, nm_mun, uf, area_ha_ibge, ST_Multi(geometry)::geometry(MultiPolygon, 4674), run_id
                FROM staging.municipios
                """
            )
        )
    log.info("Carregados %d municípios (%s)", len(gdf), uf)
    return len(gdf)


def carregar_cobertura(engine: Engine, cobertura: pd.DataFrame, run_id: str, uf: str) -> int:
    df = cobertura.copy()
    df["run_id"] = run_id
    prefixo = config.ESTADOS[uf].codigo_ibge
    with engine.begin() as con:
        con.execute(text("DROP TABLE IF EXISTS staging.cobertura_mapbiomas"))
        df.to_sql("cobertura_mapbiomas", con, schema="staging", if_exists="replace", index=False, chunksize=20_000)
        con.execute(text("DELETE FROM territorial.cobertura_mapbiomas WHERE cd_mun LIKE :p"), dict(p=f"{prefixo}%"))
        con.execute(
            text(
                """
                INSERT INTO territorial.cobertura_mapbiomas (cd_mun, ano, classe_id, classe_nome, area_ha, run_id)
                SELECT cd_mun, ano, classe_id, classe_nome, area_ha, run_id FROM staging.cobertura_mapbiomas
                """
            )
        )
    log.info("Carregadas %d linhas de cobertura (%s)", len(df), uf)
    return len(df)
