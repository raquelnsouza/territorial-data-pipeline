# Rodar sem Docker

Duas opções, conforme o que você quer mostrar.

## Opção 1 — No seu Windows, só com Python (mais simples)
Roda **a mesma lógica** do pipeline (baixar → detectar mudança → tratar → validar → gravar → auditar →
relatório), mas **sem Airflow e sem banco**: a saída são arquivos.

```powershell
cd "C:\caminho\para\territorial-data-pipeline"
powershell -ExecutionPolicy Bypass -File .\scripts\rodar_local.ps1 -MapbiomasUrl "https://drive.google.com/uc?id=SEU_ID&export=download"
```

Precisa de Python 3.10–3.12 instalado (python.org, marcando *Add python.exe to PATH*). A primeira execução cria
a pasta `.venv` e instala as bibliotecas; as seguintes são rápidas.

O que aparece na pasta `saida\`:

| Arquivo | Para quê |
|---|---|
| `territorial_PA.gpkg` | municípios (polígonos) + cobertura MapBiomas. Abre no QGIS e no Power BI (via conector GeoPackage/ODBC) |
| `relatorio\index.html` | mapa, validações e histórico (abre sozinho no navegador) |
| `audit\atualizacoes.jsonl` | histórico: data, fonte, checksum, linhas, status |
| `audit\validacoes.jsonl` | resultado de cada regra em cada execução |
| `raw\` | arquivos brutos baixados (guarda as últimas versões) |

Para demonstrar os três comportamentos (ótimo para o vídeo):

```powershell
# 1) primeira carga
...\rodar_local.ps1 -MapbiomasUrl "..."
# 2) de novo, sem mudança na fonte → "Nada a fazer"
...\rodar_local.ps1 -MapbiomasUrl "..."
# 3) falha de validação simulada → bloqueia, registra FALHOU, mantém o arquivo anterior
...\rodar_local.ps1 -MapbiomasUrl "..." -ForcarFalha -Recarregar
```

Para rodar a cada semana sozinho, use o **Agendador de Tarefas do Windows** apontando para o `.ps1`.

**Limite:** esta opção não mostra o Airflow (interface, grafo de tarefas, logs). Para isso, use a Opção 2 ou o
Docker em outro computador.

## Opção 2 — Airflow completo na nuvem (GitHub Codespaces)
Roda o projeto inteiro (Airflow + PostGIS) num computador temporário do GitHub, pelo navegador. Nada é instalado
no seu PC.

1. Crie a configuração do Codespaces: na pasta do projeto, `mkdir .devcontainer` e copie `scripts\devcontainer.json` para
   `.devcontainer\devcontainer.json` (o `scripts\devcontainer.json` é o mesmo arquivo; ele fica fora da pasta oculta só
   porque as ferramentas que uso não escrevem lá). Depois suba o projeto para um repositório no GitHub (o `.env` fica de fora,
   o `.gitignore` já cuida disso).
2. No repositório: **Code → Codespaces → Create codespace on main**. O projeto sobe sozinho
   (arquivo `.devcontainer\devcontainer.json`), levando alguns minutos.
3. Antes, cadastre o link do MapBiomas como segredo: GitHub → *Settings → Codespaces → Secrets* →
   `MAPBIOMAS_URL`. (Ou edite `MAPBIOMAS_URL` no `.env` dentro do Codespace e rode `bash scripts/codespaces.sh`.)
4. Na aba **PORTAS**, abra o endereço da porta 8080. Usuário `admin`; a senha aparece no terminal.
5. Dispare o DAG `territorial_update` e grave o vídeo.

O plano gratuito do GitHub tem um limite mensal de horas de Codespaces (confira no site). O ambiente desliga sozinho
quando fica parado, então serve para demonstrar e gravar, não como link permanente.
