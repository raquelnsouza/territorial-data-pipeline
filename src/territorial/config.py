"""Configuração central do pipeline.

Tudo o que muda de ambiente para ambiente (URLs, UF, tolerâncias) fica aqui,
para que adicionar uma nova base ou outro estado seja uma mudança de
configuração e não de código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- caminhos
DATA_DIR = Path(os.environ.get("TERRITORIAL_DATA_DIR", "/opt/airflow/data"))
RAW_DIR = DATA_DIR / "raw"
# Quantas versões brutas manter por base (arquivos grandes semanais enchem o disco).
RAW_RETENCAO = int(os.environ.get("TERRITORIAL_RAW_RETENCAO", "3"))
REPORT_DIR = Path(os.environ.get("TERRITORIAL_REPORT_DIR", "/opt/airflow/reports"))

# ----------------------------------------------------------- conexão banco
# Nome da conexão do Airflow (definida via AIRFLOW_CONN_POSTGIS_TERRITORIAL).
POSTGIS_CONN_ID = "postgis_territorial"

# ------------------------------------------------------------------- IBGE
# IBGE_API_BASE existe para testes (servidor falso local); em produção usa o padrão.
IBGE_API_BASE = os.environ.get("IBGE_API_BASE", "https://servicodados.ibge.gov.br").rstrip("/")
IBGE_LOCALIDADES_URL = IBGE_API_BASE + "/api/v1/localidades/estados/{uf}/municipios"
IBGE_MALHA_URL = (
    IBGE_API_BASE + "/api/v3/malhas/estados/{uf}"
    "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"
)

# CRS oficial brasileiro (SIRGAS 2000) e um CRS de área para o cálculo em hectares.
CRS_GEOGRAFICO = "EPSG:4674"
CRS_AREA = "EPSG:5880"  # SIRGAS 2000 / Brazil Polyconic


@dataclass(frozen=True)
class Estado:
    sigla: str
    codigo_ibge: str
    n_municipios: int  # usado na validação (contagem esperada)


ESTADOS = {
    "PA": Estado("PA", "15", 144),
    "AM": Estado("AM", "13", 62),
    "AC": Estado("AC", "12", 22),
    "RO": Estado("RO", "11", 52),
    "MT": Estado("MT", "51", 142),
}

# ---------------------------------------------------------------- MapBiomas
# A tabela de estatísticas por município do MapBiomas é um .xlsx publicado em
# cada coleção. A URL muda a cada coleção, por isso ela é lida de uma Variable do
# Airflow (MAPBIOMAS_URL) ou da variável de ambiente.
MAPBIOMAS_URL_ENV = "MAPBIOMAS_URL"
MAPBIOMAS_ARQUIVO_LOCAL_ENV = "MAPBIOMAS_ARQUIVO_LOCAL"  # alternativa: arquivo já baixado
MAPBIOMAS_ABA = os.environ.get("MAPBIOMAS_ABA", "COVERAGE_10")

# Nomes de coluna aceitos (a ordem é a prioridade). Se a coleção mudar o nome, basta
# acrescentar aqui.
MAPBIOMAS_COLUNAS_ID_MUNICIPIO = ("geocode", "cd_mun", "cod_municipio", "municipality_id")
MAPBIOMAS_COLUNAS_CLASSE_ID = ("class_id", "class", "classe_id")
MAPBIOMAS_COLUNAS_CLASSE_NOME = ("class_name", "class_level_4", "class_level_3", "classe")

# Classe de cobertura usada no mapa-resumo (3 = Formação Florestal na legenda MapBiomas).
CLASSE_FLORESTA_ID = 3


# ---------------------------------------------------------------- validação
@dataclass(frozen=True)
class RegrasValidacao:
    # Município: diferença máxima aceita entre a soma das classes do MapBiomas e a
    # área do polígono do IBGE (as duas bases usam malhas ligeiramente diferentes).
    tolerancia_area_pct: float = 5.0
    # Fração mínima de municípios do IBGE que precisa existir no MapBiomas.
    cobertura_minima_join: float = 0.99
    ano_minimo: int = 1985
    ano_maximo: int = 2100


REGRAS = RegrasValidacao()


@dataclass
class Execucao:
    """Parâmetros de uma execução (vêm dos params do DAG)."""

    uf: str = "PA"
    forcar_falha_validacao: bool = False  # demonstra o alerta de falha
    ignorar_checksum: bool = False  # reprocessa mesmo sem mudança na fonte
    extras: dict = field(default_factory=dict)
