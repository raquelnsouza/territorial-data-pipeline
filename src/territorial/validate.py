"""Validação: regras que decidem se um dado pode entrar no banco.

Cada regra devolve um ``Resultado``. Severidade ``ERRO`` bloqueia a carga (o banco
mantém a versão anterior, que continua válida); ``AVISO`` entra no relatório mas não
bloqueia. Todas as regras ficam registradas na tabela de auditoria.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import geopandas as gpd
import pandas as pd

from . import config

ERRO = "ERRO"
AVISO = "AVISO"
OK = "OK"


@dataclass
class Resultado:
    regra: str
    status: str  # OK | AVISO | ERRO
    detalhe: str


class ValidacaoFalhou(Exception):
    """Pelo menos uma regra com severidade ERRO falhou."""

    def __init__(self, resultados: list[Resultado]):
        self.resultados = resultados
        erros = [r for r in resultados if r.status == ERRO]
        super().__init__("; ".join(f"[{r.regra}] {r.detalhe}" for r in erros))


def _r(regra: str, ok: bool, detalhe_ok: str, detalhe_falha: str, severidade: str = ERRO) -> Resultado:
    return Resultado(regra, OK if ok else severidade, detalhe_ok if ok else detalhe_falha)


# --------------------------------------------------------------- municípios
def validar_municipios(gdf: gpd.GeoDataFrame, uf: str) -> list[Resultado]:
    estado = config.ESTADOS[uf]
    res: list[Resultado] = []

    n = len(gdf)
    res.append(_r("municipios.contagem", n == estado.n_municipios,
                  f"{n} municípios (esperado {estado.n_municipios})",
                  f"{n} municípios, esperado {estado.n_municipios} para {uf}"))

    dup = int(gdf["cd_mun"].duplicated().sum())
    res.append(_r("municipios.codigo_unico", dup == 0, "códigos únicos", f"{dup} códigos duplicados"))

    ruim = gdf[~gdf["cd_mun"].str.fullmatch(rf"{estado.codigo_ibge}\d{{5}}")]
    res.append(_r("municipios.codigo_formato", ruim.empty,
                  f"todos com 7 dígitos começando em {estado.codigo_ibge}",
                  f"{len(ruim)} códigos fora do padrão, ex.: {list(ruim['cd_mun'].head(3))}"))

    sem_nome = int(gdf["nm_mun"].isna().sum())
    res.append(_r("municipios.nome_preenchido", sem_nome == 0, "todos com nome", f"{sem_nome} sem nome"))

    crs_ok = gdf.crs is not None and gdf.crs.to_epsg() == 4674
    res.append(_r("municipios.crs_sirgas2000", crs_ok, "EPSG:4674", f"CRS inesperado: {gdf.crs}"))

    vazias = int(gdf.geometry.is_empty.sum() + gdf.geometry.isna().sum())
    res.append(_r("municipios.geometria_presente", vazias == 0, "nenhuma geometria vazia", f"{vazias} geometrias vazias/nulas"))

    invalidas = int((~gdf.geometry.is_valid).sum())
    res.append(_r("municipios.geometria_valida", invalidas == 0, "todas as geometrias válidas",
                  f"{invalidas} geometrias inválidas (autointerseção etc.)"))

    # Caixa do estado: ajuda a pegar arquivo errado (ex.: malha de outra UF).
    minx, miny, maxx, maxy = gdf.total_bounds
    no_brasil = -75 <= minx <= maxx <= -30 and -35 <= miny <= maxy <= 6
    res.append(_r("municipios.dentro_do_brasil", no_brasil, "coordenadas dentro do Brasil",
                  f"caixa fora do Brasil: {minx:.2f},{miny:.2f},{maxx:.2f},{maxy:.2f}"))
    return res


# ---------------------------------------------------------------- cobertura
def validar_cobertura(cobertura: pd.DataFrame, municipios: gpd.GeoDataFrame) -> list[Resultado]:
    regras = config.REGRAS
    res: list[Resultado] = []

    res.append(_r("cobertura.nao_vazia", len(cobertura) > 0, f"{len(cobertura)} linhas", "tabela vazia após filtrar a UF"))
    if cobertura.empty:
        return res

    nulos = int(cobertura["area_ha"].isna().sum() + cobertura["classe_id"].isna().sum())
    res.append(_r("cobertura.sem_nulos", nulos == 0, "sem valores nulos", f"{nulos} valores nulos em área/classe"))

    neg = int((cobertura["area_ha"] < 0).sum())
    res.append(_r("cobertura.area_nao_negativa", neg == 0, "sem áreas negativas", f"{neg} áreas negativas"))

    anos_ruins = cobertura[(cobertura["ano"] < regras.ano_minimo) | (cobertura["ano"] > regras.ano_maximo)]
    res.append(_r("cobertura.anos_plausiveis", anos_ruins.empty,
                  f"anos de {cobertura['ano'].min()} a {cobertura['ano'].max()}",
                  f"anos fora do intervalo: {sorted(anos_ruins['ano'].unique())[:5]}"))

    # Cobertura do join: quantos municípios do IBGE existem no MapBiomas?
    ibge = set(municipios["cd_mun"])
    mb = set(cobertura["cd_mun"])
    frac = len(ibge & mb) / max(len(ibge), 1)
    faltando = sorted(ibge - mb)
    res.append(_r("cobertura.join_com_ibge", frac >= regras.cobertura_minima_join,
                  f"{frac:.1%} dos municípios do IBGE presentes",
                  f"só {frac:.1%} presentes; faltando ex.: {faltando[:5]}"))

    sobra = sorted(mb - ibge)
    res.append(_r("cobertura.sem_codigo_orfao", not sobra, "todos os códigos existem no IBGE",
                  f"{len(sobra)} códigos do MapBiomas não existem no IBGE, ex.: {sobra[:5]}", AVISO))

    # Consistência cruzada: soma das classes ≈ área do polígono do IBGE.
    ultimo = cobertura[cobertura["ano"] == cobertura["ano"].max()]
    soma = ultimo.groupby("cd_mun")["area_ha"].sum().rename("soma_ha")
    comp = municipios.set_index("cd_mun")[["area_ha_ibge"]].join(soma, how="inner")
    comp["dif_pct"] = ((comp["soma_ha"] - comp["area_ha_ibge"]).abs() / comp["area_ha_ibge"]) * 100
    fora = comp[comp["dif_pct"] > regras.tolerancia_area_pct]
    pior = f"{fora['dif_pct'].idxmax()} ({fora['dif_pct'].max():.1f}%)" if not fora.empty else "-"
    res.append(_r("cobertura.area_consistente_com_ibge", fora.empty,
                  f"soma das classes dentro de {regras.tolerancia_area_pct}% da área do IBGE em todos os municípios",
                  f"{len(fora)} municípios acima de {regras.tolerancia_area_pct}% de diferença; pior caso: {pior}",
                  AVISO))
    return res


# ------------------------------------------------------------------ síntese
def consolidar(resultados: list[Resultado], forcar_falha: bool = False) -> list[Resultado]:
    """Levanta ``ValidacaoFalhou`` se houver ERRO. ``forcar_falha`` serve para demonstrar o alerta."""
    if forcar_falha:
        resultados = resultados + [
            Resultado("demo.falha_simulada", ERRO, "falha simulada pelo parâmetro forcar_falha_validacao")
        ]
    if any(r.status == ERRO for r in resultados):
        raise ValidacaoFalhou(resultados)
    return resultados


def como_dicts(resultados: list[Resultado]) -> list[dict]:
    return [asdict(r) for r in resultados]
