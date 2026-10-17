"""Dados sintéticos para testar as regras sem depender de internet nem de banco."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from territorial import config


@pytest.fixture
def municipios() -> gpd.GeoDataFrame:
    """144 'municípios' quadrados (grade 12x12) com códigos válidos do Pará."""
    linhas = []
    for i in range(144):
        x, y = -55.0 + (i % 12) * 0.1, -3.0 + (i // 12) * 0.1
        linhas.append({"cd_mun": f"15{i:05d}", "nm_mun": f"Municipio {i}", "uf": "PA", "geometry": box(x, y, x + 0.1, y + 0.1)})
    gdf = gpd.GeoDataFrame(linhas, crs=config.CRS_GEOGRAFICO)
    gdf["area_ha_ibge"] = gdf.to_crs(config.CRS_AREA).geometry.area / 10_000.0
    return gdf[["cd_mun", "nm_mun", "uf", "area_ha_ibge", "geometry"]]


@pytest.fixture
def cobertura(municipios) -> pd.DataFrame:
    """Floresta (3), pastagem (15) e água (33) somando exatamente a área do município."""
    linhas = []
    for _, m in municipios.iterrows():
        for ano in (2022, 2023):
            for classe, fr in ((3, 0.6), (15, 0.3), (33, 0.1)):
                linhas.append({"cd_mun": m.cd_mun, "ano": ano, "classe_id": classe,
                               "classe_nome": f"classe {classe}", "area_ha": m.area_ha_ibge * fr})
    return pd.DataFrame(linhas)


@pytest.fixture
def mapbiomas_largo() -> pd.DataFrame:
    """Imita a tabela larga do MapBiomas: um município em dois biomas + um município de outra UF."""
    return pd.DataFrame(
        {
            "feature_id": [1, 2, 3, 4],
            "biome": ["Amazônia", "Cerrado", "Amazônia", "Amazônia"],
            "geocode": ["1500107", "1500107", "1500206", "1300029"],  # último é do Amazonas
            "class_id": [3, 3, 15, 3],
            "class_level_4": ["Formação Florestal"] * 2 + ["Pastagem", "Formação Florestal"],
            "2022": [100.0, 50.0, 80.0, 999.0],
            "2023": [90.0, 40.0, 85.0, 999.0],
        }
    )
