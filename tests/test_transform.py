import json

import pandas as pd
import pytest

from territorial import transform


def test_mapbiomas_filtra_uf_soma_biomas_e_vira_formato_longo(mapbiomas_largo):
    longo = transform.mapbiomas_para_longo(mapbiomas_largo, "PA")
    assert set(longo["cd_mun"]) == {"1500107", "1500206"}  # município do AM saiu
    floresta_2022 = longo[(longo.cd_mun == "1500107") & (longo.ano == 2022) & (longo.classe_id == 3)]
    assert floresta_2022["area_ha"].iloc[0] == 150.0  # 100 (Amazônia) + 50 (Cerrado)
    assert set(longo.columns) == {"cd_mun", "ano", "classe_id", "area_ha", "classe_nome"}
    assert longo["ano"].dtype.kind == "i"


def test_mapbiomas_aceita_codigo_numerico_com_ponto_zero(mapbiomas_largo):
    mapbiomas_largo["geocode"] = [1500107.0, 1500107.0, 1500206.0, 1300029.0]
    assert "1500107" in set(transform.mapbiomas_para_longo(mapbiomas_largo, "PA")["cd_mun"])


def test_mapbiomas_coluna_obrigatoria_ausente_da_erro_claro(mapbiomas_largo):
    with pytest.raises(transform.ErroDeFormato, match="código do município"):
        transform.mapbiomas_para_longo(mapbiomas_largo.drop(columns=["geocode"]), "PA")


def test_mapbiomas_sem_colunas_de_ano_da_erro_claro(mapbiomas_largo):
    with pytest.raises(transform.ErroDeFormato, match="ano"):
        transform.mapbiomas_para_longo(mapbiomas_largo.drop(columns=["2022", "2023"]), "PA")


def test_montar_municipios_a_partir_dos_arquivos_do_ibge(tmp_path, municipios):
    geo = municipios.head(3).rename(columns={"cd_mun": "codarea"})[["codarea", "geometry"]]
    malha = tmp_path / "malha.geojson"
    geo.to_file(malha, driver="GeoJSON")
    locs = tmp_path / "municipios.json"
    locs.write_text(json.dumps([{"id": int(c), "nome": f"Cidade {c}"} for c in municipios.cd_mun.head(3)]), encoding="utf-8")

    gdf = transform.montar_municipios(malha, locs, "PA")
    assert list(gdf.columns) == ["cd_mun", "nm_mun", "uf", "area_ha_ibge", "geometry"]
    assert gdf.crs.to_epsg() == 4674
    assert gdf["nm_mun"].notna().all()
    assert (gdf["area_ha_ibge"] > 0).all()


def test_malha_sem_codarea_da_erro_claro(tmp_path, municipios):
    malha = tmp_path / "malha.geojson"
    municipios.head(2)[["cd_mun", "geometry"]].to_file(malha, driver="GeoJSON")
    locs = tmp_path / "m.json"
    locs.write_text("[]")
    with pytest.raises(transform.ErroDeFormato, match="codarea"):
        transform.montar_municipios(malha, locs, "PA")


def test_resumo_percentual_de_floresta(municipios, cobertura):
    r = transform.resumo_por_municipio(municipios, cobertura, classe_id=3)
    assert r["ano"].eq(2023).all()
    assert r["pct_classe"].round(1).eq(60.0).all()


def test_ler_mapbiomas_usa_aba_coverage_mesmo_com_nome_diferente(tmp_path, mapbiomas_largo):
    arq = tmp_path / "t.xlsx"
    with pd.ExcelWriter(arq) as w:
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="LEGENDA", index=False)
        mapbiomas_largo.to_excel(w, sheet_name="COVERAGE_11", index=False)
    longo = transform.ler_mapbiomas(arq, "PA")  # aba configurada (COVERAGE_10) não existe
    assert len(longo) > 0


def test_ler_mapbiomas_sem_aba_de_cobertura_da_erro_claro(tmp_path, mapbiomas_largo):
    arq = tmp_path / "t.xlsx"
    mapbiomas_largo.to_excel(arq, sheet_name="OUTRA", index=False)
    with pytest.raises(transform.ErroDeFormato, match="OUTRA"):
        transform.ler_mapbiomas(arq, "PA")
