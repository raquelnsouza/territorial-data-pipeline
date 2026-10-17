import pytest
from shapely.geometry import Polygon

from territorial import validate
from territorial.validate import AVISO, ERRO, OK


def por_regra(resultados):
    return {r.regra: r for r in resultados}


def test_dados_corretos_passam(municipios, cobertura):
    res = validate.validar_municipios(municipios, "PA") + validate.validar_cobertura(cobertura, municipios)
    assert all(r.status == OK for r in res), [r for r in res if r.status != OK]
    validate.consolidar(res)  # não levanta


def test_contagem_errada_bloqueia(municipios):
    r = por_regra(validate.validar_municipios(municipios.iloc[:100], "PA"))
    assert r["municipios.contagem"].status == ERRO


def test_codigo_duplicado_bloqueia(municipios):
    ruim = municipios.copy()
    ruim.loc[1, "cd_mun"] = ruim.loc[0, "cd_mun"]
    assert por_regra(validate.validar_municipios(ruim, "PA"))["municipios.codigo_unico"].status == ERRO


def test_codigo_de_outra_uf_bloqueia(municipios):
    ruim = municipios.copy()
    ruim.loc[0, "cd_mun"] = "1300029"
    assert por_regra(validate.validar_municipios(ruim, "PA"))["municipios.codigo_formato"].status == ERRO


def test_geometria_invalida_bloqueia(municipios):
    ruim = municipios.copy()
    gravata = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])  # autointerseção
    ruim.loc[0, "geometry"] = gravata
    assert por_regra(validate.validar_municipios(ruim, "PA"))["municipios.geometria_valida"].status == ERRO


def test_crs_errado_bloqueia(municipios):
    assert por_regra(validate.validar_municipios(municipios.to_crs("EPSG:3857"), "PA"))["municipios.crs_sirgas2000"].status == ERRO


def test_area_negativa_bloqueia(municipios, cobertura):
    cobertura.loc[0, "area_ha"] = -1
    assert por_regra(validate.validar_cobertura(cobertura, municipios))["cobertura.area_nao_negativa"].status == ERRO


def test_municipios_faltando_no_mapbiomas_bloqueia(municipios, cobertura):
    parcial = cobertura[~cobertura["cd_mun"].isin(municipios["cd_mun"].head(10))]
    assert por_regra(validate.validar_cobertura(parcial, municipios))["cobertura.join_com_ibge"].status == ERRO


def test_area_inconsistente_so_avisa(municipios, cobertura):
    cobertura["area_ha"] *= 1.5
    r = por_regra(validate.validar_cobertura(cobertura, municipios))["cobertura.area_consistente_com_ibge"]
    assert r.status == AVISO  # avisa, mas não bloqueia a carga
    validate.consolidar(validate.validar_municipios(municipios, "PA") + validate.validar_cobertura(cobertura, municipios))


def test_falha_forcada_levanta_e_guarda_todas_as_regras(municipios):
    res = validate.validar_municipios(municipios, "PA")
    with pytest.raises(validate.ValidacaoFalhou) as e:
        validate.consolidar(res, forcar_falha=True)
    assert "demo.falha_simulada" in str(e.value)
    assert len(e.value.resultados) == len(res) + 1
