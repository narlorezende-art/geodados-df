"""Fotos aéreas oficiais do GDF (IDE-DF / SEDUH) como camadas do mapa.

Os serviços do GDF estão na projeção SIRGAS 2000 / UTM 23S. O navegador pede
blocos no padrão da web (z/x/y, Web Mercator); este módulo converte o bloco num
retângulo, pede a imagem já reprojetada ao servidor do GDF (exportImage) e a
devolve ao mapa. Blocos recentes ficam guardados em memória para aliviar o GDF.
Dados públicos, sem chave: https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/Imagens
"""
from __future__ import annotations

import math
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict

URL = "https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/Imagens/{servico}/ImageServer/exportImage"

# (serviço no GDF, rótulo curto, descrição) — do mais antigo ao mais recente
SERVICOS = [
    ("FOTO_1964", "1964", "Foto aérea"),
    ("FOTO_1975", "1975", "Foto aérea"),
    ("FOTO_1980", "1980", "Foto aérea"),
    ("FOTO_1986", "1986", "Foto aérea"),
    ("FOTO_1991", "1991", "Foto aérea"),
    ("FOTO_1997", "1997", "Foto aérea"),
    ("QUICKBIRD_2007", "2007", "Satélite QuickBird"),
    ("FOTO_2009", "2009", "Foto aérea"),
    ("FOTO_2013", "2013", "Foto aérea"),
    ("FOTO_2015", "2015", "Foto aérea"),
    ("FOTO_2016", "2016", "Foto aérea"),
    ("PLEIADES_2017", "2017", "Satélite Pléiades"),
    ("GEOEYE_TERRACAP_2018", "2018", "Satélite GeoEye (Terracap)"),
    ("2021_50CM", "2021", "Imagem 50 cm"),
    ("2022_50CM_MAXAR", "2022", "Satélite Maxar 50 cm"),
    ("FOTO_AEREA_2023", "2023", "Foto aérea"),
    ("FOTO_AEREA_2024", "2024", "Foto aérea 8 cm"),
]
PERMITIDOS = {s[0] for s in SERVICOS}
MAIS_RECENTE = "FOTO_AEREA_2024"

# Retângulo do DF com folga (graus): só esses blocos são pedidos ao GDF
DF_LON = (-48.35, -47.25)
DF_LAT = (-16.10, -15.45)
ZOOM_MIN, ZOOM_MAX = 8, 21

_R = 6378137.0
_trava = threading.Lock()
_cache: "OrderedDict[tuple, tuple[bytes, str]]" = OrderedDict()
_cache_bytes = 0
CACHE_MAX_BYTES = 60 * 1024 * 1024

# PNG 1x1 transparente, para blocos fora do DF
VAZIO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
)


def info() -> list[dict]:
    """Lista enviada ao navegador para montar a linha do tempo."""
    return [{"id": s, "ano": a, "tipo": t} for s, a, t in SERVICOS]


def _lon_lat_para_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = math.radians(lon) * _R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R
    return x, y


def bbox_do_bloco(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Retângulo (xmin, ymin, xmax, ymax) em Web Mercator (EPSG:3857) do bloco z/x/y."""
    lado = 2 * math.pi * _R / (2 ** z)
    origem = math.pi * _R
    xmin = -origem + x * lado
    ymax = origem - y * lado
    return xmin, ymax - lado, xmin + lado, ymax


def bloco_no_df(z: int, x: int, y: int) -> bool:
    xmin, ymin, xmax, ymax = bbox_do_bloco(z, x, y)
    dx0, dy0 = _lon_lat_para_mercator(DF_LON[0], DF_LAT[0])
    dx1, dy1 = _lon_lat_para_mercator(DF_LON[1], DF_LAT[1])
    return xmax > dx0 and xmin < dx1 and ymax > dy0 and ymin < dy1


def _baixar(servico: str, z: int, x: int, y: int) -> tuple[bytes, str]:
    xmin, ymin, xmax, ymax = bbox_do_bloco(z, x, y)
    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": 3857, "imageSR": 3857, "size": "256,256",
        "format": "jpgpng", "transparent": "true",
        "interpolation": "RSP_BilinearInterpolation", "f": "image",
    }
    req = urllib.request.Request(
        URL.format(servico=servico) + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "CCOTRAN-DF/1.0 (painel privado)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        tipo = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        corpo = resp.read()
    if not tipo.startswith("image/"):
        raise RuntimeError("O GDF devolveu uma resposta que não é imagem.")
    return corpo, tipo


def bloco(servico: str, z: int, x: int, y: int, baixar=None) -> tuple[bytes, str]:
    """Imagem do bloco. Levanta ValueError para pedidos inválidos."""
    global _cache_bytes
    if servico not in PERMITIDOS:
        raise ValueError("Camada desconhecida.")
    if not (0 <= z <= ZOOM_MAX and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("Bloco fora do intervalo.")
    if z < ZOOM_MIN or not bloco_no_df(z, x, y):   # muito longe ou fora do DF: bloco vazio
        return VAZIO, "image/png"
    chave = (servico, z, x, y)
    with _trava:
        if chave in _cache:
            _cache.move_to_end(chave)
            return _cache[chave]
    dados = (baixar or _baixar)(servico, z, x, y)
    with _trava:
        _cache[chave] = dados
        _cache_bytes += len(dados[0])
        while _cache_bytes > CACHE_MAX_BYTES and _cache:
            _, (b, _t) = _cache.popitem(last=False)
            _cache_bytes -= len(b)
    return dados


def limpar_cache() -> None:
    global _cache_bytes
    with _trava:
        _cache.clear()
        _cache_bytes = 0
