FROM apache/airflow:2.10.5-python3.12

# Pastas de trabalho com a dona certa, para os volumes nomeados herdarem a permissão.
USER root
RUN mkdir -p /opt/airflow/data /opt/airflow/reports && chown -R airflow:root /opt/airflow/data /opt/airflow/reports
USER airflow

# Dependências geoespaciais. As rodas (wheels) já trazem GDAL/GEOS/PROJ embutidos,
# então não é preciso instalar bibliotecas do sistema.
# O arquivo de constraints do Airflow evita conflito de versões com o que já está na imagem.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt"

# Código da lógica de negócio fica em /opt/airflow/src e entra no PYTHONPATH.
ENV PYTHONPATH="/opt/airflow/src:${PYTHONPATH}"
