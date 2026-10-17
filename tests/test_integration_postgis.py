"""Teste de integração com PostGIS real. Roda só se TEST_POSTGIS_URL estiver definida.

Ex.: TEST_POSTGIS_URL=postgresql+psycopg2://territorial:x@localhost:5455/territorial pytest
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from territorial import audit, load, report
from territorial.extract import ArquivoBruto

URL = os.environ.get("TEST_POSTGIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_POSTGIS_URL não definida")

INIT_SQL = Path(__file__).parent.parent / "sql" / "init.sql"


@pytest.fixture
def engine():
    eng = create_engine(URL)
    with eng.begin() as con:
        con.exec_driver_sql(INIT_SQL.read_text())
        con.exec_driver_sql(
            "TRUNCATE territorial.municipios, territorial.cobertura_mapbiomas, audit.atualizacoes, audit.validacoes"
        )
    yield eng
    eng.dispose()


def contar(engine, tabela):
    with engine.connect() as con:
        return con.execute(text(f"SELECT count(*) FROM {tabela}")).scalar()


def arquivo(base="mapbiomas_municipios", sha="abc"):
    return ArquivoBruto(base=base, caminho="/x", fonte="teste", sha256=sha, tamanho_bytes=1, baixado_em="2026-10-17T00:00:00+00:00")


def test_carga_e_recarga_sao_idempotentes(engine, municipios, cobertura):
    for _ in range(2):  # carregar duas vezes não duplica
        assert load.carregar_municipios(engine, municipios, "run1", "PA") == 144
        assert load.carregar_cobertura(engine, cobertura, "run1", "PA") == len(cobertura)
    assert contar(engine, "territorial.municipios") == 144
    assert contar(engine, "territorial.cobertura_mapbiomas") == len(cobertura)
    with engine.connect() as con:
        assert con.execute(text("SELECT DISTINCT ST_SRID(geometry) FROM territorial.municipios")).scalar() == 4674
        assert con.execute(text("SELECT count(*) FROM territorial.v_cobertura_municipio")).scalar() == len(cobertura)


def test_carga_com_erro_nao_estraga_a_versao_anterior(engine, municipios, cobertura):
    load.carregar_cobertura(engine, cobertura, "bom", "PA")
    ruim = cobertura.copy()
    ruim.loc[0, "classe_id"] = None  # viola NOT NULL no meio da carga
    with pytest.raises(Exception):
        load.carregar_cobertura(engine, ruim, "ruim", "PA")
    assert contar(engine, "territorial.cobertura_mapbiomas") == len(cobertura)
    with engine.connect() as con:
        assert con.execute(text("SELECT DISTINCT run_id FROM territorial.cobertura_mapbiomas")).scalar() == "bom"


def test_deteccao_de_mudanca_por_checksum(engine):
    a = arquivo(sha="v1")
    assert audit.houve_mudanca(engine, [a])  # nunca carregado
    audit.registrar_arquivo(engine, "r1", a, "CARREGADO", linhas=10)
    assert not audit.houve_mudanca(engine, [a])  # mesmo checksum
    assert audit.houve_mudanca(engine, [arquivo(sha="v2")])  # fonte mudou


def test_relatorio_html_tem_mapa_e_historico(engine, municipios, cobertura, tmp_path):
    from territorial.validate import Resultado

    load.carregar_municipios(engine, municipios, "r1", "PA")
    load.carregar_cobertura(engine, cobertura, "r1", "PA")
    audit.registrar_arquivo(engine, "r1", arquivo(), "CARREGADO", linhas=len(cobertura))
    audit.registrar_validacoes(engine, "r1", [Resultado("municipios.contagem", "OK", "144")])
    saida = report.gerar(engine, "PA", tmp_path / "index.html")
    html = saida.read_text(encoding="utf-8")
    assert html.count('"cd_mun"') == 144
    assert "municipios.contagem" in html and "CARREGADO" in html
