"""Extração: baixa as fontes, guarda o arquivo bruto e calcula o checksum.

Regra de ouro de rastreabilidade: o arquivo bruto baixado é sempre salvo em
``raw/<base>/<timestamp>/`` com o seu SHA-256. Assim, qualquer número do banco pode
ser conferido contra o que a fonte realmente entregou naquele dia.
"""
from __future__ import annotations

import hashlib
import html as _html
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config

log = logging.getLogger(__name__)

TIMEOUT = (10, 120)  # (conexão, leitura) em segundos
USER_AGENT = "territorial-data-pipeline/1.0 (+atualizacao-automatica-de-bases)"


@dataclass
class ArquivoBruto:
    base: str
    caminho: str
    fonte: str
    sha256: str
    tamanho_bytes: int
    baixado_em: str  # ISO 8601 UTC


def sha256_de_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _pasta_da_execucao(base: str, raw_dir: Path | None = None) -> Path:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pasta = (raw_dir or config.RAW_DIR) / base / carimbo
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


class ErroDownload(RuntimeError):
    """O download não entregou o arquivo esperado (ex.: página de erro no lugar do arquivo)."""


# ----------------------------------------------------------------- Google Drive
_DRIVE_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
_DRIVE_ID = re.compile(r"(?:/file/d/|[?&]id=)([A-Za-z0-9_-]{20,})")


def eh_google_drive(url: str) -> bool:
    return (urlparse(url).hostname or "") in _DRIVE_HOSTS


def normalizar_url_drive(url: str) -> str:
    """Aceita os formatos de link do Drive (``/file/d/ID/view``, ``open?id=ID``, ``uc?id=ID``)."""
    m = _DRIVE_ID.search(url)
    if not m:
        raise ErroDownload(f"Não achei o ID do arquivo no link do Google Drive: {url}")
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}"


def _atributo(tag: str, nome: str) -> str | None:
    m = re.search(rf'\b{nome}\s*=\s*"([^"]*)"', tag)
    return _html.unescape(m.group(1)) if m else None


def _formulario_de_confirmacao(pagina: str) -> tuple[str, dict] | None:
    """Arquivos grandes: o Drive responde com uma página HTML ("não foi possível verificar
    vírus") cujo formulário leva ao download real. Extrai o destino e os campos ocultos."""
    f = re.search(r"<form\b[^>]*>", pagina)
    if f and (acao := _atributo(f.group(0), "action")):
        campos = {}
        for tag in re.findall(r"<input\b[^>]*>", pagina):
            nome = _atributo(tag, "name")
            if nome:
                campos[nome] = _atributo(tag, "value") or ""
        return acao, campos
    # formato antigo: link com ?confirm=TOKEN
    m = re.search(r"confirm=([0-9A-Za-z_-]+)", _html.unescape(pagina))
    if m:
        return "https://drive.google.com/uc", {"export": "download", "confirm": m.group(1)}
    return None


def _eh_html(r: requests.Response) -> bool:
    return "text/html" in r.headers.get("Content-Type", "").lower()


def _mensagem_drive(pagina: str) -> str:
    baixa = pagina.lower()
    if "quota" in baixa or "too many users" in baixa:
        return ("O Google Drive bloqueou o download por excesso de acessos (cota diária do arquivo). "
                "Tente novamente mais tarde ou copie o arquivo para outra conta/pasta.")
    if "sign in" in baixa or "accounts.google.com" in baixa or "request access" in baixa:
        return ("O Google Drive pediu login: o arquivo precisa estar compartilhado como "
                "'Qualquer pessoa com o link'.")
    return "O Google Drive devolveu uma página HTML em vez do arquivo (link, permissão ou cota)."


def _gravar(r: requests.Response, destino: Path) -> None:
    parcial = destino.with_suffix(destino.suffix + ".part")
    try:
        with open(parcial, "wb") as f:
            for bloco in r.iter_content(chunk_size=1024 * 1024):
                f.write(bloco)
        esperado = r.headers.get("Content-Length")
        if esperado and parcial.stat().st_size != int(esperado) and not r.headers.get("Content-Encoding"):
            raise ErroDownload(f"Download incompleto: {parcial.stat().st_size} de {esperado} bytes")
        parcial.replace(destino)  # só vira o arquivo final se terminou inteiro
    finally:
        parcial.unlink(missing_ok=True)


def baixar(url: str, destino: Path, sessao: requests.Session | None = None) -> None:
    """Baixa ``url`` em streaming para ``destino``. Levanta erro em qualquer status != 2xx.

    Para links do Google Drive, normaliza o link e atravessa a página de confirmação
    que o Drive mostra em arquivos grandes.
    """
    s = sessao or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    drive = eh_google_drive(url)
    if drive:
        url = normalizar_url_drive(url)

    with s.get(url, stream=True, timeout=TIMEOUT, headers=headers) as r:
        r.raise_for_status()
        if not (drive and _eh_html(r)):
            _gravar(r, destino)
            return
        pagina = r.text  # página pequena (aviso do Drive)

    alvo = _formulario_de_confirmacao(pagina)
    if not alvo:
        raise ErroDownload(_mensagem_drive(pagina))
    acao, campos = alvo
    log.info("Google Drive pediu confirmação (arquivo grande); seguindo para o download real")
    with s.get(acao, params=campos, stream=True, timeout=TIMEOUT, headers=headers) as r2:
        r2.raise_for_status()
        if _eh_html(r2):
            raise ErroDownload(_mensagem_drive(r2.text))
        _gravar(r2, destino)


# ---------------------------------------------------------------- limpeza de disco
def descartar_download(arq: "ArquivoBruto") -> None:
    """Apaga a pasta de um download que não será usado (fonte não mudou). O registro de
    auditoria (checksum, data, tamanho) permanece no banco."""
    shutil.rmtree(Path(arq.caminho).parent, ignore_errors=True)


def limpar_raw(base: str, manter: int | None = None, raw_dir: Path | None = None) -> list[str]:
    """Mantém só as ``manter`` versões brutas mais recentes de ``base`` (arquivos grandes
    semanais encheriam o disco da VPS)."""
    manter = config.RAW_RETENCAO if manter is None else manter
    pasta = (raw_dir or config.RAW_DIR) / base
    if not pasta.is_dir():
        return []
    versoes = sorted(p for p in pasta.iterdir() if p.is_dir())
    removidas = versoes[:-manter] if manter > 0 else versoes
    for p in removidas:
        shutil.rmtree(p, ignore_errors=True)
    return [p.name for p in removidas]


def _registrar(base: str, caminho: Path, fonte: str) -> ArquivoBruto:
    return ArquivoBruto(
        base=base,
        caminho=str(caminho),
        fonte=fonte,
        sha256=sha256_de_arquivo(caminho),
        tamanho_bytes=caminho.stat().st_size,
        baixado_em=datetime.now(timezone.utc).isoformat(),
    )


def extrair_ibge_malha(uf: str, raw_dir: Path | None = None) -> ArquivoBruto:
    estado = config.ESTADOS[uf]
    url = config.IBGE_MALHA_URL.format(uf=estado.codigo_ibge)
    destino = _pasta_da_execucao(f"ibge_malha_{uf}", raw_dir) / "malha_municipios.geojson"
    log.info("Baixando malha municipal do IBGE: %s", url)
    baixar(url, destino)
    return _registrar(f"ibge_malha_{uf}", destino, url)


def extrair_ibge_localidades(uf: str, raw_dir: Path | None = None) -> ArquivoBruto:
    estado = config.ESTADOS[uf]
    url = config.IBGE_LOCALIDADES_URL.format(uf=estado.codigo_ibge)
    destino = _pasta_da_execucao(f"ibge_localidades_{uf}", raw_dir) / "municipios.json"
    log.info("Baixando lista de municípios do IBGE: %s", url)
    baixar(url, destino)
    return _registrar(f"ibge_localidades_{uf}", destino, url)


def extrair_mapbiomas(raw_dir: Path | None = None, url: str | None = None,
                      arquivo_local: str | None = None) -> ArquivoBruto:
    """Baixa a tabela de estatísticas por município do MapBiomas.

    Duas formas de informar a fonte (nesta ordem):
    1. ``arquivo_local`` (ou env ``MAPBIOMAS_ARQUIVO_LOCAL``): caminho de um .xlsx já
       baixado (cópia para a pasta bruta, para manter a rastreabilidade);
    2. ``url`` (ou env ``MAPBIOMAS_URL``): link direto do .xlsx.
    No Airflow, os dois valores vêm das Variables de mesmo nome.
    """
    destino_dir = _pasta_da_execucao("mapbiomas_municipios", raw_dir)
    local = arquivo_local or os.environ.get(config.MAPBIOMAS_ARQUIVO_LOCAL_ENV)
    if local:
        origem = Path(local)
        if not origem.is_file():
            raise FileNotFoundError(f"MAPBIOMAS_ARQUIVO_LOCAL não existe: {origem}")
        destino = destino_dir / origem.name
        shutil.copy2(origem, destino)
        return _registrar("mapbiomas_municipios", destino, f"arquivo-local:{origem.name}")

    url = url or os.environ.get(config.MAPBIOMAS_URL_ENV)
    if not url:
        raise RuntimeError(
            "Fonte do MapBiomas não configurada. Defina a Variable do Airflow "
            "MAPBIOMAS_URL (ou a variável de ambiente) com o link do .xlsx — "
        )
    destino = destino_dir / "mapbiomas_municipios.xlsx"
    log.info("Baixando estatísticas do MapBiomas: %s", url)
    baixar(url, destino)
    _conferir_xlsx(destino)
    return _registrar("mapbiomas_municipios", destino, url)


def _conferir_xlsx(caminho: Path) -> None:
    """.xlsx é um zip: começa com 'PK'. Pega o caso de salvar uma página de erro como arquivo."""
    with open(caminho, "rb") as f:
        if f.read(2) != b"PK":
            raise ErroDownload(
                f"O arquivo baixado ({caminho.stat().st_size} bytes) não é um .xlsx válido. "
                "Confira o link e se o compartilhamento está como 'Qualquer pessoa com o link'."
            )
