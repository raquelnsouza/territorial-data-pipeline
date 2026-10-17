"""DAG: atualização automatizada de bases territoriais (IBGE + MapBiomas).

Fluxo:
    extrair_ibge ─┐
                  ├─► detectar_mudanca ─► transformar_e_validar ─► carregar ─► publicar_relatorio
    extrair_mapbiomas ┘

* ``detectar_mudanca`` compara o checksum de cada fonte com o da última carga bem
  sucedida; se nada mudou, o restante é pulado (registrado como SEM_MUDANCA).
* ``transformar_e_validar`` aplica as regras de validação e bloqueia a carga se
  alguma regra de severidade ERRO falhar.
* ``carregar`` é transacional: ou entra tudo, ou continua a versão anterior.
* Em qualquer falha, ``notificar_falha`` registra na auditoria e envia e-mail.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.models import Variable
from airflow.models.param import Param
from airflow.operators.python import get_current_context
from airflow.providers.postgres.hooks.postgres import PostgresHook

from territorial import audit, config, extract, load, report, transform, validate
from territorial.alerts import notificar_falha

log = logging.getLogger(__name__)


def _engine():
    return PostgresHook(postgres_conn_id=config.POSTGIS_CONN_ID).get_sqlalchemy_engine()


@dag(
    dag_id="territorial_update",
    description="Atualiza malha municipal (IBGE) e cobertura do solo (MapBiomas) no PostGIS",
    schedule="@weekly",  # a rotina verifica toda semana; só recarrega se a fonte mudou
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Belem"),
    catchup=False,
    max_active_runs=1,
    tags=["territorial", "ibge", "mapbiomas", "demo"],
    default_args={
        "owner": "dados",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "on_failure_callback": notificar_falha,
    },
    params={
        "uf": Param("PA", enum=sorted(config.ESTADOS), description="UF a atualizar"),
        "forcar_falha_validacao": Param(False, type="boolean",
                                        description="Demonstração: força uma falha de validação para ver o alerta"),
        "ignorar_checksum": Param(False, type="boolean",
                                  description="Reprocessa mesmo que as fontes não tenham mudado"),
    },
    doc_md=__doc__,
)
def territorial_update():
    @task
    def extrair_ibge() -> list[dict]:
        uf = get_current_context()["params"]["uf"]
        arquivos = [extract.extrair_ibge_malha(uf), extract.extrair_ibge_localidades(uf)]
        return [a.__dict__ for a in arquivos]

    @task(execution_timeout=timedelta(minutes=60))  # arquivo grande: dá tempo, mas não fica preso para sempre
    def extrair_mapbiomas() -> list[dict]:
        url = Variable.get("MAPBIOMAS_URL", default_var=None)
        local = Variable.get("MAPBIOMAS_ARQUIVO_LOCAL", default_var=None)
        return [extract.extrair_mapbiomas(url=url, arquivo_local=local).__dict__]

    @task.short_circuit
    def detectar_mudanca(ibge: list[dict], mapbiomas: list[dict]) -> bool:
        ctx = get_current_context()
        run_id, params = ctx["run_id"], ctx["params"]
        arquivos = [extract.ArquivoBruto(**d) for d in ibge + mapbiomas]
        engine = _engine()
        mudou = params["ignorar_checksum"] or audit.houve_mudanca(engine, arquivos)
        for a in arquivos:
            audit.registrar_arquivo(engine, run_id, a, "BAIXADO" if mudou else "SEM_MUDANCA")
        if not mudou:
            log.info("Nenhuma fonte mudou desde a última carga. Nada a fazer.")
            for a in arquivos:  # não guarda cópia repetida de arquivo grande; o registro fica na auditoria
                extract.descartar_download(a)
        return bool(mudou)

    @task
    def transformar_e_validar(ibge: list[dict], mapbiomas: list[dict]) -> dict:
        ctx = get_current_context()
        run_id, params = ctx["run_id"], ctx["params"]
        uf = params["uf"]
        engine = _engine()

        malha = next(d for d in ibge if d["base"].startswith("ibge_malha"))
        locs = next(d for d in ibge if d["base"].startswith("ibge_localidades"))
        municipios = transform.montar_municipios(Path(malha["caminho"]), Path(locs["caminho"]), uf)
        cobertura = transform.ler_mapbiomas(Path(mapbiomas[0]["caminho"]), uf)

        resultados = validate.validar_municipios(municipios, uf) + validate.validar_cobertura(cobertura, municipios)
        # Grava o resultado das regras ANTES de decidir se bloqueia: o histórico fica completo.
        try:
            validate.consolidar(resultados, forcar_falha=params["forcar_falha_validacao"])
        except validate.ValidacaoFalhou as e:
            audit.registrar_validacoes(engine, run_id, e.resultados)
            raise AirflowFailException(f"Validação bloqueou a carga: {e}") from e
        audit.registrar_validacoes(engine, run_id, resultados)

        pasta = config.DATA_DIR / "processed" / run_id.replace(":", "_").replace("+", "_")
        pasta.mkdir(parents=True, exist_ok=True)
        municipios.to_file(pasta / "municipios.gpkg", driver="GPKG")
        cobertura.to_csv(pasta / "cobertura.csv.gz", index=False)
        avisos = [r.regra for r in resultados if r.status == validate.AVISO]
        return {"pasta": str(pasta), "n_municipios": len(municipios), "n_cobertura": len(cobertura), "avisos": avisos}

    @task
    def carregar(processado: dict, ibge: list[dict], mapbiomas: list[dict]) -> dict:
        import geopandas as gpd
        import pandas as pd

        ctx = get_current_context()
        run_id, uf = ctx["run_id"], ctx["params"]["uf"]
        engine = _engine()
        pasta = Path(processado["pasta"])
        municipios = gpd.read_file(pasta / "municipios.gpkg")
        cobertura = pd.read_csv(pasta / "cobertura.csv.gz", dtype={"cd_mun": str})

        n_mun = load.carregar_municipios(engine, municipios, run_id, uf)
        n_cob = load.carregar_cobertura(engine, cobertura, run_id, uf)

        linhas = {"ibge_malha": n_mun, "ibge_localidades": n_mun, "mapbiomas": n_cob}
        for d in ibge + mapbiomas:
            arq = extract.ArquivoBruto(**d)
            chave = next(k for k in linhas if arq.base.startswith(k))
            audit.registrar_arquivo(engine, run_id, arq, "CARREGADO", linhas=linhas[chave],
                                    detalhe=f"avisos: {processado['avisos']}" if processado["avisos"] else None)
            extract.limpar_raw(arq.base)  # mantém só as últimas versões brutas
        return {"municipios": n_mun, "cobertura": n_cob}

    @task
    def publicar_relatorio(_resultado: dict) -> str:
        uf = get_current_context()["params"]["uf"]
        return str(report.gerar(_engine(), uf))

    ibge = extrair_ibge()
    mapbiomas = extrair_mapbiomas()
    mudou = detectar_mudanca(ibge, mapbiomas)
    processado = transformar_e_validar(ibge, mapbiomas)
    mudou >> processado
    publicar_relatorio(carregar(processado, ibge, mapbiomas))


territorial_update()
