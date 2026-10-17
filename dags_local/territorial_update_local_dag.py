"""DAG (versão SEM BANCO): mesma lógica do DAG principal, gravando em arquivos.

Para rodar o Airflow sem Docker e sem PostGIS (ex.: WSL com `airflow standalone`).
Saídas em $TERRITORIAL_SAIDA (padrão ~/territorial_saida):
    territorial_<UF>.gpkg · audit/*.jsonl · relatorio/index.html · raw/

Fluxo:
    extrair_ibge ─┐
                  ├─► detectar_mudanca ─► transformar_e_validar ─► gravar ─► publicar_relatorio
    extrair_mapbiomas ┘
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.models import Variable
from airflow.models.param import Param
from airflow.operators.python import get_current_context

from territorial import config, extract, local_run, transform, validate

log = logging.getLogger(__name__)


def _saida() -> Path:
    return Path(os.environ.get("TERRITORIAL_SAIDA", str(Path.home() / "territorial_saida")))


def notificar_falha(contexto: dict) -> None:
    """Registra a falha no histórico (arquivo) e, se ALERT_EMAIL + SMTP estiverem configurados, envia e-mail."""
    ti, erro = contexto["task_instance"], str(contexto.get("exception", "erro desconhecido"))
    log.error("[FALHA] %s / %s: %s", ti.dag_id, ti.task_id, erro)
    try:
        local_run.registrar_evento(_saida(), contexto["run_id"], f"tarefa:{ti.task_id}", "FALHOU", erro)
    except Exception:  # o alerta nunca pode falhar por causa da auditoria
        log.exception("Não foi possível gravar a falha no histórico")
    if os.environ.get("ALERT_EMAIL"):
        try:
            from airflow.utils.email import send_email

            send_email(to=[e.strip() for e in os.environ["ALERT_EMAIL"].split(",")],
                       subject=f"[FALHA] {ti.dag_id} / {ti.task_id}",
                       html_content=f"{erro}<br><br>A versão anterior dos dados foi mantida.")
        except Exception:
            log.exception("Falha ao enviar o e-mail de alerta")


@dag(
    dag_id="territorial_update_local",
    description="Atualiza malha municipal (IBGE) e cobertura do solo (MapBiomas) em arquivos (sem banco)",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Manaus"),
    catchup=False,
    max_active_runs=1,
    tags=["territorial", "ibge", "mapbiomas", "sem-banco"],
    default_args={"owner": "dados", "retries": 2, "retry_delay": timedelta(minutes=5),
                  "on_failure_callback": notificar_falha},
    params={
        "uf": Param("PA", enum=sorted(config.ESTADOS), description="UF a atualizar"),
        "forcar_falha_validacao": Param(False, type="boolean", description="Demonstração: força uma falha de validação"),
        "ignorar_checksum": Param(False, type="boolean", description="Reprocessa mesmo que as fontes não tenham mudado"),
    },
    doc_md=__doc__,
)
def territorial_update_local():
    @task
    def extrair_ibge() -> list[dict]:
        uf = get_current_context()["params"]["uf"]
        raw = _saida() / "raw"
        return [a.__dict__ for a in (extract.extrair_ibge_malha(uf, raw), extract.extrair_ibge_localidades(uf, raw))]

    @task(execution_timeout=timedelta(minutes=60))
    def extrair_mapbiomas() -> list[dict]:
        url = Variable.get("MAPBIOMAS_URL", default_var=None) or os.environ.get("MAPBIOMAS_URL")
        local = Variable.get("MAPBIOMAS_ARQUIVO_LOCAL", default_var=None)
        return [extract.extrair_mapbiomas(_saida() / "raw", url=url, arquivo_local=local).__dict__]

    @task.short_circuit
    def detectar_mudanca(ibge: list[dict], mapbiomas: list[dict]) -> bool:
        ctx = get_current_context()
        run_id, saida = ctx["run_id"], _saida()
        arquivos = [extract.ArquivoBruto(**d) for d in ibge + mapbiomas]
        mudou = ctx["params"]["ignorar_checksum"] or any(
            local_run.ultimo_checksum(saida, a.base) != a.sha256 for a in arquivos)
        for a in arquivos:
            local_run.registrar_arquivo(saida, run_id, a, "BAIXADO" if mudou else "SEM_MUDANCA")
            if not mudou:
                extract.descartar_download(a)  # não guarda cópia repetida de arquivo grande
        if not mudou:
            log.info("Nenhuma fonte mudou desde a última carga. Nada a fazer.")
        return bool(mudou)

    @task
    def transformar_e_validar(ibge: list[dict], mapbiomas: list[dict]) -> dict:
        ctx = get_current_context()
        run_id, uf, saida = ctx["run_id"], ctx["params"]["uf"], _saida()
        malha = next(d for d in ibge if d["base"].startswith("ibge_malha"))
        locs = next(d for d in ibge if d["base"].startswith("ibge_localidades"))
        municipios = transform.montar_municipios(Path(malha["caminho"]), Path(locs["caminho"]), uf)
        cobertura = transform.ler_mapbiomas(Path(mapbiomas[0]["caminho"]), uf)

        resultados = validate.validar_municipios(municipios, uf) + validate.validar_cobertura(cobertura, municipios)
        try:
            validate.consolidar(resultados, forcar_falha=ctx["params"]["forcar_falha_validacao"])
        except validate.ValidacaoFalhou as e:
            local_run.registrar_validacoes(saida, run_id, e.resultados)
            raise AirflowFailException(f"Validação bloqueou a carga: {e}") from e
        local_run.registrar_validacoes(saida, run_id, resultados)

        pasta = saida / "processed" / run_id.replace(":", "_").replace("+", "_")
        pasta.mkdir(parents=True, exist_ok=True)
        municipios.to_file(pasta / "municipios.gpkg", driver="GPKG")
        cobertura.to_csv(pasta / "cobertura.csv.gz", index=False)
        return {"pasta": str(pasta), "n_municipios": len(municipios), "n_cobertura": len(cobertura),
                "avisos": [r.regra for r in resultados if r.status == validate.AVISO]}

    @task
    def gravar(processado: dict, ibge: list[dict], mapbiomas: list[dict]) -> dict:
        import geopandas as gpd
        import pandas as pd

        ctx = get_current_context()
        run_id, uf, saida = ctx["run_id"], ctx["params"]["uf"], _saida()
        pasta = Path(processado["pasta"])
        municipios = gpd.read_file(pasta / "municipios.gpkg")
        cobertura = pd.read_csv(pasta / "cobertura.csv.gz", dtype={"cd_mun": str})

        gpkg = local_run.gravar_gpkg(saida, uf, municipios, cobertura, run_id)  # troca atômica do arquivo
        linhas = {"ibge_malha": len(municipios), "ibge_localidades": len(municipios), "mapbiomas": len(cobertura)}
        for d in ibge + mapbiomas:
            arq = extract.ArquivoBruto(**d)
            chave = next(k for k in linhas if arq.base.startswith(k))
            local_run.registrar_arquivo(saida, run_id, arq, "CARREGADO", linhas=linhas[chave],
                                        detalhe=f"avisos: {processado['avisos']}" if processado["avisos"] else None)
            extract.limpar_raw(arq.base, raw_dir=saida / "raw")
        return {"gpkg": str(gpkg), "municipios": len(municipios), "cobertura": len(cobertura)}

    @task
    def publicar_relatorio(resultado: dict, processado: dict) -> str:
        import geopandas as gpd
        import pandas as pd

        ctx = get_current_context()
        pasta = Path(processado["pasta"])
        municipios = gpd.read_file(pasta / "municipios.gpkg")
        cobertura = pd.read_csv(pasta / "cobertura.csv.gz", dtype={"cd_mun": str})
        return str(local_run.gerar_relatorio(_saida(), ctx["params"]["uf"], municipios, cobertura, ctx["run_id"]))

    ibge, mapbiomas = extrair_ibge(), extrair_mapbiomas()
    mudou = detectar_mudanca(ibge, mapbiomas)
    processado = transformar_e_validar(ibge, mapbiomas)
    mudou >> processado
    publicar_relatorio(gravar(processado, ibge, mapbiomas), processado)


territorial_update_local()
