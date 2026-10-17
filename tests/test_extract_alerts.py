import hashlib

import pytest

from territorial import alerts, extract


def test_sha256_confere_com_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"conteudo")
    assert extract.sha256_de_arquivo(f) == hashlib.sha256(b"conteudo").hexdigest()


def test_mapbiomas_arquivo_local_e_copiado_com_checksum(tmp_path):
    origem = tmp_path / "tabela.xlsx"
    origem.write_bytes(b"xlsx-falso")
    arq = extract.extrair_mapbiomas(raw_dir=tmp_path / "raw", arquivo_local=str(origem))
    assert arq.base == "mapbiomas_municipios"
    assert arq.sha256 == hashlib.sha256(b"xlsx-falso").hexdigest()
    assert arq.caminho != str(origem)  # cópia na pasta bruta, original intacto
    assert origem.exists()


def test_mapbiomas_sem_fonte_configurada_explica_o_que_fazer(tmp_path, monkeypatch):
    monkeypatch.delenv("MAPBIOMAS_URL", raising=False)
    monkeypatch.delenv("MAPBIOMAS_ARQUIVO_LOCAL", raising=False)
    with pytest.raises(RuntimeError, match="MAPBIOMAS_URL"):
        extract.extrair_mapbiomas(raw_dir=tmp_path)


def test_mensagem_de_alerta_diz_o_que_aconteceu_e_que_o_dado_anterior_foi_mantido():
    assunto, corpo = alerts.montar_mensagem("territorial_update", "transformar_e_validar", "manual__1", "erro X", "http://log")
    assert "FALHA" in assunto and "transformar_e_validar" in assunto
    assert "erro X" in corpo and "http://log" in corpo and "mantida" in corpo


# ------------------------------------------------------------------ Google Drive
import http.server
import threading

from territorial import extract


@pytest.fixture
def servidor_drive(monkeypatch):
    """Servidor local que imita o Drive: arquivo grande → página de confirmação → arquivo real."""
    conteudo = b"PK\x03\x04" + b"x" * 5000  # parece um .xlsx (zip)
    modo = {"valor": "confirmacao"}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/uc") and "confirm=t" not in self.path:
                if modo["valor"] == "cota":
                    corpo = b"<html>Sorry, you can't view or download this file. Too many users have downloaded</html>"
                elif modo["valor"] == "login":
                    corpo = b'<html><a href="https://accounts.google.com/ServiceLogin">Sign in</a></html>'
                else:
                    corpo = (b'<html><form id="download-form" action="http://127.0.0.1:%d/baixar" method="get">'
                             b'<input type="hidden" name="id" value="ABC"><input type="hidden" name="export" value="download">'
                             b'<input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="u-1">'
                             b'</form></html>' % self.server.server_port)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(corpo)
            elif self.path.startswith("/baixar"):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(conteudo)))
                self.end_headers()
                self.wfile.write(conteudo)
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(extract, "_DRIVE_HOSTS", {"127.0.0.1"})
    monkeypatch.setattr(extract, "normalizar_url_drive", lambda u: u)
    yield f"http://127.0.0.1:{srv.server_port}/uc?id=ABC&export=download", conteudo, modo
    srv.shutdown()


def test_drive_arquivo_grande_atravessa_pagina_de_confirmacao(servidor_drive, tmp_path):
    url, conteudo, _ = servidor_drive
    destino = tmp_path / "t.xlsx"
    extract.baixar(url, destino)
    assert destino.read_bytes() == conteudo
    assert not list(tmp_path.glob("*.part"))  # sem lixo


def test_drive_cota_excedida_da_mensagem_clara(servidor_drive, tmp_path):
    url, _, modo = servidor_drive
    modo["valor"] = "cota"
    with pytest.raises(extract.ErroDownload, match="cota"):
        extract.baixar(url, tmp_path / "t.xlsx")
    assert not (tmp_path / "t.xlsx").exists()


def test_drive_pedindo_login_explica_compartilhamento(servidor_drive, tmp_path):
    url, _, modo = servidor_drive
    modo["valor"] = "login"
    with pytest.raises(extract.ErroDownload, match="Qualquer pessoa com o link"):
        extract.baixar(url, tmp_path / "t.xlsx")


def test_normaliza_formatos_de_link_do_drive():
    id_ = "1otOqymHuixvkRGVl65zTTNyfaHo46Gqk"
    esperado = f"https://drive.google.com/uc?export=download&id={id_}"
    for link in (f"https://drive.google.com/uc?id={id_}&export=download",
                 f"https://drive.google.com/file/d/{id_}/view?usp=sharing",
                 f"https://drive.google.com/open?id={id_}"):
        assert extract.normalizar_url_drive(link) == esperado
    assert extract.eh_google_drive(link) and not extract.eh_google_drive("https://servicodados.ibge.gov.br/x")


def test_arquivo_que_nao_e_xlsx_e_rejeitado(tmp_path):
    ruim = tmp_path / "pagina.xlsx"
    ruim.write_bytes(b"<html>erro</html>")
    with pytest.raises(extract.ErroDownload, match="não é um .xlsx"):
        extract._conferir_xlsx(ruim)


def test_limpeza_mantem_so_as_versoes_mais_recentes(tmp_path):
    base = tmp_path / "mapbiomas_municipios"
    for carimbo in ("20260101", "20260108", "20260115", "20260122"):
        (base / carimbo).mkdir(parents=True)
        (base / carimbo / "a.xlsx").write_bytes(b"PK")
    removidas = extract.limpar_raw("mapbiomas_municipios", manter=2, raw_dir=tmp_path)
    assert removidas == ["20260101", "20260108"]
    assert sorted(p.name for p in base.iterdir()) == ["20260115", "20260122"]


def test_descartar_download_remove_a_pasta(tmp_path):
    pasta = tmp_path / "x" / "t1"
    pasta.mkdir(parents=True)
    f = pasta / "a.xlsx"
    f.write_bytes(b"PK")
    arq = extract.ArquivoBruto("b", str(f), "u", "sha", 2, "2026-01-01")
    extract.descartar_download(arq)
    assert not pasta.exists()
