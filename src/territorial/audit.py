"""Rastreabilidade: grava no banco o que foi baixado, validado e carregado."""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .extract import ArquivoBruto
from .validate import Resultado

log = logging.getLogger(__name__)


def registrar_arquivo(engine: Engine, run_id: str, arq: ArquivoBruto, status: str,
                      linhas: int | None = None, detalhe: str | None = None) -> None:
    with engine.begin() as con:
        con.execute(
            text(
                """
                INSERT INTO audit.atualizacoes
                  (run_id, base, fonte, arquivo_bruto, sha256, tamanho_bytes, baixado_em, linhas, status, detalhe)
                VALUES (:run_id, :base, :fonte, :arquivo, :sha, :tam, :baixado, :linhas, :status, :detalhe)
                """
            ),
            dict(run_id=run_id, base=arq.base, fonte=arq.fonte, arquivo=arq.caminho, sha=arq.sha256,
                 tam=arq.tamanho_bytes, baixado=arq.baixado_em, linhas=linhas, status=status, detalhe=detalhe),
        )


def registrar_evento(engine: Engine, run_id: str, base: str, status: str, detalhe: str | None = None) -> None:
    """Evento sem arquivo (ex.: falha antes do download)."""
    with engine.begin() as con:
        con.execute(
            text("INSERT INTO audit.atualizacoes (run_id, base, status, detalhe) VALUES (:r, :b, :s, :d)"),
            dict(r=run_id, b=base, s=status, d=detalhe),
        )


def registrar_validacoes(engine: Engine, run_id: str, resultados: Iterable[Resultado]) -> None:
    with engine.begin() as con:
        for r in resultados:
            con.execute(
                text("INSERT INTO audit.validacoes (run_id, regra, status, detalhe) VALUES (:run, :regra, :status, :detalhe)"),
                dict(run=run_id, regra=r.regra, status=r.status, detalhe=r.detalhe),
            )


def ultimo_checksum_carregado(engine: Engine, base: str) -> str | None:
    with engine.connect() as con:
        row = con.execute(
            text("SELECT sha256 FROM audit.atualizacoes WHERE base = :b AND status = 'CARREGADO' "
                 "ORDER BY criado_em DESC LIMIT 1"),
            dict(b=base),
        ).first()
    return row[0] if row else None


def houve_mudanca(engine: Engine, arquivos: Iterable[ArquivoBruto]) -> bool:
    """True se qualquer base tem checksum diferente do último carregado com sucesso."""
    for arq in arquivos:
        anterior = ultimo_checksum_carregado(engine, arq.base)
        if anterior != arq.sha256:
            log.info("Mudança detectada em %s (antes=%s, agora=%s)", arq.base, anterior, arq.sha256)
            return True
    return False
