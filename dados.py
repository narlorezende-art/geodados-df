"""Lê a planilha CSV dos equipamentos e entrega a lista pronta para o mapa.

Colunas esperadas: COD. RA, RA, ID EQUIP, ENDEREÇO, TIPO, LATITUDE, LONGITUDE
O arquivo equipamentos.csv fica na mesma pasta; para atualizar, basta trocá-lo no GitHub.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

CSV_PADRAO = Path(__file__).resolve().parent / "equipamentos.csv"

NOMES_RA = {
    "BRASILIA": "Plano Piloto (Brasília)", "CEILANDIA": "Ceilândia", "TAGUATINGA": "Taguatinga",
    "SAMAMBAIA": "Samambaia", "GAMA": "Gama", "GUARA": "Guará", "LAGO SUL": "Lago Sul",
    "PLANALTINA": "Planaltina", "SANTA MARIA": "Santa Maria", "SUDOESTE/OCTOGONAL": "Sudoeste/Octogonal",
    "SAO SEBASTIAO": "São Sebastião", "AGUAS CLARAS": "Águas Claras", "SOBRADINHO": "Sobradinho",
    "RECANTO DAS EMAS": "Recanto das Emas", "PARANOA": "Paranoá", "CRUZEIRO": "Cruzeiro",
    "JARDIM BOTANICO": "Jardim Botânico", "SOBRADINHO II": "Sobradinho II", "BRAZLANDIA": "Brazlândia",
    "SCIA": "SCIA/Estrutural",
}
TIPOS = {
    "CONTROLADOR ELETRÔNICO": "CE",
    "REDUTOR ELETRÔNICO DE VELOCIDADE": "RE",
    "NÃO METROLÓGICO": "NM",
}
SENTIDOS_CARDEAIS = {"NORTE/SUL", "SUL/NORTE", "LESTE/OESTE", "OESTE/LESTE"}
_RE_SENTIDO = re.compile(r"(?:SENTIDO|SENT\.?)\s*([A-ZÇÃÉÍ]+)\s*/\s*([A-ZÇÃÉÍ]+)")

_cache: dict = {"mtime": None, "caminho": None, "itens": []}


def limpar_endereco(texto: str) -> str:
    texto = texto.replace("ÿ", " ").replace('""', '"')
    texto = re.sub(r"<\s*$", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def extrair_sentido(endereco: str) -> str:
    m = _RE_SENTIDO.search(endereco.upper())
    chave = f"{m.group(1)}/{m.group(2)}" if m else ""
    return chave if chave in SENTIDOS_CARDEAIS else "OUTRO"


def _coluna(linha: dict, *nomes: str) -> str:
    for n in nomes:
        if n in linha:
            return (linha[n] or "").strip()
    raise KeyError(f"Coluna não encontrada: {nomes[0]}")


def ler_csv(caminho: Path = CSV_PADRAO) -> list[dict]:
    itens = []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        amostra = f.read(4096)
        f.seek(0)
        separador = ";" if amostra.count(";") > amostra.count(",") else ","
        for linha in csv.DictReader(f, delimiter=separador):
            linha = {(k or "").strip().upper(): v for k, v in linha.items()}
            try:
                lat = float(_coluna(linha, "LATITUDE").replace(",", "."))
                lon = float(_coluna(linha, "LONGITUDE").replace(",", "."))
            except ValueError:
                continue  # linha sem coordenada válida
            endereco = limpar_endereco(_coluna(linha, "ENDEREÇO", "ENDERECO"))
            ra = _coluna(linha, "RA")
            tipo = _coluna(linha, "TIPO").upper()
            itens.append({
                "id": _coluna(linha, "ID EQUIP"),
                "cra": int(_coluna(linha, "COD. RA", "COD RA") or 0),
                "ra": NOMES_RA.get(ra.upper(), ra.title()),
                "end": endereco,
                "t": TIPOS.get(tipo, "NM"),
                "s": extrair_sentido(endereco),
                "lat": round(lat, 7),
                "lon": round(lon, 7),
            })
    return itens


def equipamentos(caminho: Path = CSV_PADRAO) -> list[dict]:
    """Lista em cache; relê o CSV se o arquivo mudou."""
    mtime = caminho.stat().st_mtime
    if _cache["mtime"] != mtime or _cache["caminho"] != caminho:
        _cache.update(mtime=mtime, caminho=caminho, itens=ler_csv(caminho))
    return _cache["itens"]
