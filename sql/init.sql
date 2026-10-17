-- Executado automaticamente na primeira subida do banco PostGIS.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS territorial;  -- dados prontos para uso pela ferramenta
CREATE SCHEMA IF NOT EXISTS staging;      -- área de passagem (recriada a cada carga)
CREATE SCHEMA IF NOT EXISTS audit;        -- rastreabilidade das atualizações

-- Malha municipal (IBGE) já padronizada em SIRGAS 2000.
CREATE TABLE IF NOT EXISTS territorial.municipios (
    cd_mun        CHAR(7) PRIMARY KEY,
    nm_mun        TEXT NOT NULL,
    uf            CHAR(2) NOT NULL,
    area_ha_ibge  DOUBLE PRECISION NOT NULL,
    geometry      geometry(MultiPolygon, 4674) NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id        TEXT
);
CREATE INDEX IF NOT EXISTS municipios_geom_idx ON territorial.municipios USING GIST (geometry);

-- Cobertura e uso da terra (MapBiomas) em formato longo.
CREATE TABLE IF NOT EXISTS territorial.cobertura_mapbiomas (
    cd_mun        CHAR(7) NOT NULL,
    ano           SMALLINT NOT NULL,
    classe_id     SMALLINT NOT NULL,
    classe_nome   TEXT,
    area_ha       DOUBLE PRECISION NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id        TEXT,
    PRIMARY KEY (cd_mun, ano, classe_id)
);

-- Visão pronta para o Power BI / QGIS: junta as duas bases pelo código IBGE.
CREATE OR REPLACE VIEW territorial.v_cobertura_municipio AS
SELECT m.cd_mun, m.nm_mun, m.uf, c.ano, c.classe_id, c.classe_nome, c.area_ha,
       m.area_ha_ibge,
       100.0 * c.area_ha / NULLIF(m.area_ha_ibge, 0) AS pct_da_area_ibge
FROM territorial.cobertura_mapbiomas c
JOIN territorial.municipios m USING (cd_mun);

-- Registro de cada base processada em cada execução.
CREATE TABLE IF NOT EXISTS audit.atualizacoes (
    id            BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL,
    base          TEXT NOT NULL,
    fonte         TEXT,
    arquivo_bruto TEXT,
    sha256        TEXT,
    tamanho_bytes BIGINT,
    baixado_em    TIMESTAMPTZ,
    linhas        BIGINT,
    status        TEXT NOT NULL,   -- BAIXADO | SEM_MUDANCA | CARREGADO | FALHOU
    detalhe       TEXT,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS atualizacoes_base_idx ON audit.atualizacoes (base, criado_em DESC);

-- Resultado de cada regra de validação em cada execução.
CREATE TABLE IF NOT EXISTS audit.validacoes (
    id        BIGSERIAL PRIMARY KEY,
    run_id    TEXT NOT NULL,
    regra     TEXT NOT NULL,
    status    TEXT NOT NULL,       -- OK | AVISO | ERRO
    detalhe   TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS validacoes_run_idx ON audit.validacoes (run_id);
