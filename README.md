# Pipeline de atualização automatizada de bases territoriais

Case de engenharia de dados: uma rotina em **Airflow** que mantém atualizadas bases públicas e
geoespaciais — **IBGE** (malha municipal) e **MapBiomas** (cobertura e uso da terra) — num banco
**PostGIS**, com validação, rastreabilidade, alertas de falha e uma página-resumo com mapa.

## O que ele faz

```
 IBGE (malha municipal) ─┐
 IBGE (nomes)            ├─► detecta mudança ─► trata + valida ─► carrega no PostGIS ─► página-resumo
 MapBiomas (Drive)      ─┘     (checksum)        (15 regras)      (transacional)        (mapa + histórico)
                                   │                  │                  │
                                   └──────────── auditoria (quem, quando, de onde, o quê) ─────────┘
                                   Falhou? → registra + avisa por e-mail; o dado anterior é mantido.
```

## Competências

| Tema | Onde está |
|---|---|
| Levantamento de fonte, formato, periodicidade e acesso | `src/territorial/config.py`, `docs/MAPBIOMAS_FONTE.md` |
| **Validação** dos dados (CRS, geometrias, códigos, consistência entre bases) | `src/territorial/validate.py` |
| **Rastreabilidade** das atualizações | tabelas `audit.*`; arquivo bruto com SHA-256 |
| **Periodicidade** e atualização só quando a fonte muda | `schedule="@weekly"` + checagem de checksum |
| **Tratamento e padronização** | `src/territorial/transform.py` (SIRGAS 2000, código IBGE de 7 dígitos, formato longo) |
| Arquivos grandes (download do Drive, leitura em streaming, limpeza de disco) | `extract.py`, `transform.py` |
| **Alerta** de falha | `src/territorial/alerts.py` |
| **Testes** (unitários, integração com PostGIS real, ponta a ponta) | `tests/` (36 testes) |
| Infraestrutura como código (Docker, HTTPS, usuário somente leitura) | `docker-compose.yml`, `Caddyfile`, `scripts/` |


## Estrutura

```
dags/territorial_update_dag.py   o fluxo (fino: só orquestra)
src/territorial/                 a lógica (testável sem Airflow)
  config.py extract.py transform.py validate.py load.py audit.py alerts.py report.py local_run.py
sql/init.sql                     tabelas, visão e auditoria
tests/                           pytest + teste de integração com PostGIS
scripts/                         bootstrap.sh/deploy.ps1 (servidor), rodar_local.ps1 (Windows sem Docker), codespaces.sh
docker-compose.yml Dockerfile Caddyfile   Airflow + PostGIS + HTTPS
```

## Decisões de projeto

* **Lógica fora do DAG.** O DAG só orquestra; tudo o que importa está em funções puras e testadas.
* **Carga transacional com staging.** Grava em `staging`, troca na tabela final numa transação; se falhar, fica a versão anterior.
* **Validação com severidade.** `ERRO` bloqueia a carga; `AVISO` (ex.: diferença de área entre as bases) entra no relatório mas não bloqueia.
* **Fonte bruta preservada.** Todo arquivo baixado fica guardado com checksum (com retenção das últimas versões).
* **Incluir nova base = adicionar um extrator + um conjunto de regras**, sem mexer no resto.

## Testes

```bash
pip install -r requirements.txt pytest "apache-airflow==2.10.5" apache-airflow-providers-postgres \
   --constraint https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt
pytest -q                                   # 30 testes sem banco
TEST_POSTGIS_URL=postgresql+psycopg2://usuario:senha@localhost:5433/territorial pytest -q   # + integração
python tests/e2e_local.py                   # DAG inteiro contra um servidor falso das fontes
```

## Limites

* Recorte em um estado (PA), com malha simplificada do IBGE (`qualidade=minima`). Para uso em produção:
  malha em qualidade máxima, mais bases (SICAR, SIGEF, PRODES…) e monitoramento contínuo.
* Dados de origem: IBGE e MapBiomas.
