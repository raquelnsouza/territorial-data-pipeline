"""Modo local (sem Airflow/Docker/banco), contra um servidor falso das fontes."""
import http.server
import json
import threading

import geopandas as gpd
import pytest

from territorial import local_run


@pytest.fixture
def fontes(tmp_path, municipios, cobertura, monkeypatch):
    """Sobe IBGE e MapBiomas falsos em http://127.0.0.1:<porta> com os dados sintéticos das fixtures."""
    from territorial import config

    pasta = tmp_path / "servidor"
    pasta.mkdir()
    municipios.rename(columns={"cd_mun": "codarea"})[["codarea", "geometry"]].to_file(pasta / "malha.geojson", driver="GeoJSON")
    (pasta / "locs.json").write_text(json.dumps([{"id": int(r.cd_mun), "nome": r.nm_mun} for r in municipios.itertuples()]))
    largo = cobertura.pivot_table(index=["cd_mun", "classe_id", "classe_nome"], columns="ano", values="area_ha").reset_index()
    largo.columns = [str(c) for c in largo.columns]
    largo = largo.rename(columns={"cd_mun": "geocode", "classe_nome": "class_level_4"})
    largo.to_excel(pasta / "mapbiomas.xlsx", sheet_name="COVERAGE_10", index=False)

    rotas = {"/api/v3/malhas/estados/15": "malha.geojson", "/api/v1/localidades/estados/15/municipios": "locs.json",
             "/mapbiomas.xlsx": "mapbiomas.xlsx"}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nome = rotas.get(self.path.split("?")[0])
            if not nome:
                return self.send_error(404)
            dados = (pasta / nome).read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setattr(config, "IBGE_MALHA_URL", base + "/api/v3/malhas/estados/{uf}?formato=x")
    monkeypatch.setattr(config, "IBGE_LOCALIDADES_URL", base + "/api/v1/localidades/estados/{uf}/municipios")
    yield base + "/mapbiomas.xlsx"
    srv.shutdown()


def linhas_audit(saida, nome="atualizacoes"):
    return local_run._ler(saida / "audit" / f"{nome}.jsonl")


def test_ciclo_completo_carga_sem_mudanca_falha_e_recarga(fontes, tmp_path):
    saida = tmp_path / "saida"

    # 1) primeira carga
    assert local_run.executar("PA", saida, mapbiomas_url=fontes) == 0
    gpkg = saida / "territorial_PA.gpkg"
    assert gpkg.exists() and (saida / "relatorio" / "index.html").exists()
    assert len(gpd.read_file(gpkg, layer="municipios")) == 144
    assert len(gpd.read_file(gpkg, layer="cobertura_mapbiomas")) == 144 * 3 * 2
    assert {r["status"] for r in linhas_audit(saida)} >= {"BAIXADO", "CARREGADO"}
    assert any(r["regra"] == "municipios.contagem" and r["status"] == "OK" for r in linhas_audit(saida, "validacoes"))
    antes = gpkg.stat().st_mtime_ns

    # 2) fontes iguais → nada a fazer, arquivo não é tocado
    assert local_run.executar("PA", saida, mapbiomas_url=fontes) == 0
    assert gpkg.stat().st_mtime_ns == antes
    assert linhas_audit(saida)[-1]["status"] == "SEM_MUDANCA"

    # 3) falha simulada → código 1, registro FALHOU, versão anterior intacta
    assert local_run.executar("PA", saida, mapbiomas_url=fontes, forcar_falha=True, ignorar_checksum=True) == 1
    assert linhas_audit(saida)[-1]["status"] == "FALHOU"
    assert gpkg.stat().st_mtime_ns == antes
    assert any(r["regra"] == "demo.falha_simulada" for r in linhas_audit(saida, "validacoes"))
    assert not list(saida.glob(".*.tmp.gpkg"))

    # 4) recarga forçada funciona de novo
    assert local_run.executar("PA", saida, mapbiomas_url=fontes, ignorar_checksum=True) == 0
    assert gpkg.stat().st_mtime_ns > antes


def test_fonte_do_mapbiomas_ausente_falha_com_mensagem(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MAPBIOMAS_URL", raising=False)
    monkeypatch.delenv("MAPBIOMAS_ARQUIVO_LOCAL", raising=False)
    # IBGE inalcançável também falharia; o importante é falhar limpo, registrar e devolver 1
    assert local_run.executar("PA", tmp_path / "s", mapbiomas_url=None) == 1
    assert linhas_audit(tmp_path / "s")[-1]["status"] == "FALHOU"
    assert "FALHOU" in capsys.readouterr().err
