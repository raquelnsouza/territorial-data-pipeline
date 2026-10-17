"""Execução LOCAL, sem Airflow, sem Docker e sem banco: mesma lógica do DAG, saídas em arquivos.

    python -m territorial.local_run --uf PA --mapbiomas-url "<link do Drive>"

Faz: baixar → detectar mudança (checksum) → tratar → validar → gravar → registrar auditoria → página-resumo.
Saídas (pasta ``saida/``):
    territorial_<UF>.gpkg      municípios (geometria) + cobertura MapBiomas (GeoPackage: abre no QGIS)
    audit/atualizacoes.jsonl   histórico de downloads/cargas (data, fonte, checksum, linhas, status)
    audit/validacoes.jsonl     resultado de cada regra em cada execução
    relatorio/index.html       mapa + validações + histórico
    raw/                       arquivos brutos baixados (últimas versões)

A gravação é atômica: o .gpkg anterior só é trocado quando a nova versão está completa e validada.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config, extract, report, transform, validate

log = logging.getLogger("territorial.local")


# ----------------------------------------------------------------- auditoria
def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _anexar(arquivo: Path, registro: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _ler(arquivo: Path) -> list[dict]:
    if not arquivo.exists():
        return []
    with open(arquivo, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def ultimo_checksum(saida: Path, base: str) -> str | None:
    for r in reversed(_ler(saida / "audit" / "atualizacoes.jsonl")):
        if r["base"] == base and r["status"] == "CARREGADO":
            return r["sha256"]
    return None


def registrar_arquivo(saida: Path, run_id: str, arq: extract.ArquivoBruto, status: str,
                      linhas: int | None = None, detalhe: str | None = None) -> None:
    _anexar(saida / "audit" / "atualizacoes.jsonl", dict(
        quando=_agora(), run_id=run_id, base=arq.base, fonte=arq.fonte, sha256=arq.sha256,
        tamanho_bytes=arq.tamanho_bytes, linhas=linhas, status=status, detalhe=detalhe))


def registrar_evento(saida: Path, run_id: str, base: str, status: str, detalhe: str) -> None:
    _anexar(saida / "audit" / "atualizacoes.jsonl", dict(
        quando=_agora(), run_id=run_id, base=base, fonte=None, sha256=None, tamanho_bytes=None,
        linhas=None, status=status, detalhe=detalhe[:2000]))


def registrar_validacoes(saida: Path, run_id: str, resultados: list[validate.Resultado]) -> None:
    for r in resultados:
        _anexar(saida / "audit" / "validacoes.jsonl",
                dict(quando=_agora(), run_id=run_id, regra=r.regra, status=r.status, detalhe=r.detalhe))


# ------------------------------------------------------------------- gravação
def gravar_gpkg(saida: Path, uf: str, municipios: gpd.GeoDataFrame, cobertura: pd.DataFrame, run_id: str) -> Path:
    """Escreve num arquivo temporário e só então substitui o definitivo (tudo ou nada)."""
    final = saida / f"territorial_{uf}.gpkg"
    tmp = saida / f".territorial_{uf}.tmp.gpkg"
    tmp.unlink(missing_ok=True)
    m = municipios.copy()
    m["run_id"] = run_id
    c = cobertura.copy()
    c["run_id"] = run_id
    m.to_file(tmp, layer="municipios", driver="GPKG")
    from pyogrio import write_dataframe

    write_dataframe(c, tmp, layer="cobertura_mapbiomas", driver="GPKG", append=True)  # tabela sem geometria
    os.replace(tmp, final)
    return final


def gerar_relatorio(saida: Path, uf: str, municipios: gpd.GeoDataFrame, cobertura: pd.DataFrame, run_id: str) -> Path:
    ult = pd.DataFrame(_ler(saida / "audit" / "atualizacoes.jsonl")[-12:][::-1])
    if not ult.empty:
        ult["sha256"] = ult["sha256"].fillna("").str[:12]
        ult = ult[["quando", "base", "status", "linhas", "sha256", "detalhe"]]
    val = pd.DataFrame([r for r in _ler(saida / "audit" / "validacoes.jsonl") if r["run_id"] == run_id])
    if not val.empty:
        val = val[["regra", "status", "detalhe"]]
    return report.renderizar(municipios, cobertura, ult, val, uf, saida / "relatorio" / "index.html")


# ------------------------------------------------------------------ principal
def executar(uf: str, saida: Path, mapbiomas_url: str | None = None, mapbiomas_arquivo: str | None = None,
             forcar_falha: bool = False, ignorar_checksum: bool = False) -> int:
    """Devolve 0 em sucesso (inclusive 'sem mudança') e 1 em falha."""
    saida.mkdir(parents=True, exist_ok=True)
    raw = saida / "raw"
    run_id = "local__" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    arquivos: list[extract.ArquivoBruto] = []
    try:
        log.info("1/6 Baixando as fontes")
        ibge_malha = extract.extrair_ibge_malha(uf, raw)
        ibge_locs = extract.extrair_ibge_localidades(uf, raw)
        mb = extract.extrair_mapbiomas(raw, url=mapbiomas_url, arquivo_local=mapbiomas_arquivo)
        arquivos = [ibge_malha, ibge_locs, mb]

        log.info("2/6 Verificando se alguma fonte mudou")
        mudou = ignorar_checksum or any(ultimo_checksum(saida, a.base) != a.sha256 for a in arquivos)
        if not mudou:
            for a in arquivos:
                registrar_arquivo(saida, run_id, a, "SEM_MUDANCA")
                extract.descartar_download(a)
            log.info("Nenhuma fonte mudou desde a última carga. Nada a fazer.")
            return 0
        for a in arquivos:
            registrar_arquivo(saida, run_id, a, "BAIXADO")

        log.info("3/6 Tratando e padronizando")
        municipios = transform.montar_municipios(Path(ibge_malha.caminho), Path(ibge_locs.caminho), uf)
        cobertura = transform.ler_mapbiomas(Path(mb.caminho), uf)

        log.info("4/6 Validando (%d municípios, %d linhas de cobertura)", len(municipios), len(cobertura))
        resultados = validate.validar_municipios(municipios, uf) + validate.validar_cobertura(cobertura, municipios)
        try:
            validate.consolidar(resultados, forcar_falha=forcar_falha)
        except validate.ValidacaoFalhou as e:
            registrar_validacoes(saida, run_id, e.resultados)
            raise
        registrar_validacoes(saida, run_id, resultados)

        log.info("5/6 Gravando o GeoPackage")
        gpkg = gravar_gpkg(saida, uf, municipios, cobertura, run_id)
        avisos = [r.regra for r in resultados if r.status == validate.AVISO]
        for a, n in ((ibge_malha, len(municipios)), (ibge_locs, len(municipios)), (mb, len(cobertura))):
            registrar_arquivo(saida, run_id, a, "CARREGADO", linhas=n, detalhe=f"avisos: {avisos}" if avisos else None)
            extract.limpar_raw(a.base, raw_dir=raw)

        log.info("6/6 Gerando a página-resumo")
        pagina = gerar_relatorio(saida, uf, municipios, cobertura, run_id)
        print(f"\nPRONTO.\n  Dados:     {gpkg}\n  Relatório: {pagina}\n  Histórico: {saida / 'audit'}")
        return 0
    except Exception as e:  # noqa: BLE001 - qualquer falha vira registro + código de saída 1
        log.error("FALHOU: %s", e)
        registrar_evento(saida, run_id, "pipeline", "FALHOU", f"{type(e).__name__}: {e}")
        print(f"\nFALHOU: {e}\nA versão anterior dos dados (se existir) foi mantida.", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Atualiza as bases territoriais localmente (sem Airflow/Docker).")
    p.add_argument("--uf", default="PA", choices=sorted(config.ESTADOS))
    p.add_argument("--saida", default="saida", type=Path)
    p.add_argument("--mapbiomas-url", default=os.environ.get("MAPBIOMAS_URL"), help="link do .xlsx (Drive ou outro)")
    p.add_argument("--mapbiomas-arquivo", default=os.environ.get("MAPBIOMAS_ARQUIVO_LOCAL"), help="ou um .xlsx já baixado")
    p.add_argument("--forcar-falha-validacao", action="store_true", help="demonstra o bloqueio e o registro de falha")
    p.add_argument("--ignorar-checksum", action="store_true", help="reprocessa mesmo sem mudança na fonte")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    return executar(a.uf, a.saida, a.mapbiomas_url, a.mapbiomas_arquivo, a.forcar_falha_validacao, a.ignorar_checksum)


if __name__ == "__main__":
    sys.exit(main())
