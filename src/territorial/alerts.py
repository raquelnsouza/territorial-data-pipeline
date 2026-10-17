"""Alertas de falha.

O callback é chamado pelo Airflow quando qualquer tarefa falha. Ele sempre grava um
evento FALHOU na tabela de auditoria (mesmo sem e-mail configurado) e, se
``ALERT_EMAIL`` e o SMTP do Airflow estiverem configurados, envia um e-mail.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def montar_mensagem(dag_id: str, task_id: str, run_id: str, erro: str, url_log: str | None) -> tuple[str, str]:
    assunto = f"[FALHA] {dag_id} / {task_id}"
    corpo = (
        f"A atualização automática de bases falhou.\n\n"
        f"DAG: {dag_id}\nTarefa: {task_id}\nExecução: {run_id}\n\nErro:\n{erro}\n\n"
        + (f"Log completo: {url_log}\n" if url_log else "")
        + "\nA versão anterior dos dados no banco foi mantida (a carga é transacional)."
    )
    return assunto, corpo


def notificar_falha(contexto: dict) -> None:
    from airflow.hooks.base import BaseHook  # import tardio: não exige Airflow nos testes
    from sqlalchemy import create_engine

    ti = contexto["task_instance"]
    run_id = contexto["run_id"]
    erro = str(contexto.get("exception", "erro desconhecido"))
    assunto, corpo = montar_mensagem(ti.dag_id, ti.task_id, run_id, erro, getattr(ti, "log_url", None))
    log.error("%s\n%s", assunto, corpo)

    try:
        from .audit import registrar_evento
        from . import config

        engine = BaseHook.get_connection(config.POSTGIS_CONN_ID).get_hook().get_sqlalchemy_engine()
        registrar_evento(engine, run_id, f"tarefa:{ti.task_id}", "FALHOU", erro[:2000])
    except Exception:  # o alerta nunca pode falhar por causa da auditoria
        log.exception("Não foi possível gravar a falha na auditoria")

    destino = os.environ.get("ALERT_EMAIL")
    if destino:
        try:
            from airflow.utils.email import send_email

            send_email(to=[e.strip() for e in destino.split(",")], subject=assunto, html_content=corpo.replace("\n", "<br>"))
        except Exception:
            log.exception("Falha ao enviar o e-mail de alerta (SMTP configurado?)")
