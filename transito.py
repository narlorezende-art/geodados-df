"""Trânsito em tempo real (fluxo nas vias) — TomTom Traffic Flow, blocos de mapa.

A chave TOMTOM_KEY fica só no servidor: o navegador pede /transito/z/x/y ao nosso
servidor, que busca na TomTom e guarda cada bloco por 2 minutos (economiza a cota).
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request
from collections import OrderedDict

URL = "https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key={key}&tileSize=256"
VALIDADE = 120
_trava = threading.Lock()
_cache: "OrderedDict[tuple, tuple[float, bytes]]" = OrderedDict()
MAX_ITENS = 1500
VAZIO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
)


def ativo() -> bool:
    return bool(os.environ.get("TOMTOM_KEY", "").strip())


def _baixar(z: int, x: int, y: int) -> bytes:
    url = URL.format(z=z, x=x, y=y, key=os.environ["TOMTOM_KEY"].strip())
    req = urllib.request.Request(url, headers={"User-Agent": "CCOTRAN-DF/1.0 (painel privado)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        if not resp.headers.get("Content-Type", "").startswith("image/"):
            raise RuntimeError("A TomTom não devolveu imagem.")
        return resp.read()


def bloco(z: int, x: int, y: int, baixar=None) -> bytes:
    if not ativo():
        raise PermissionError("Configure TOMTOM_KEY no Render para ativar o trânsito.")
    if not (0 <= z <= 20 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("Bloco fora do intervalo.")
    if z < 6:                      # muito afastado: não gasta cota da TomTom
        return VAZIO
    chave = (z, x, y)
    with _trava:
        item = _cache.get(chave)
        if item and time.time() - item[0] < VALIDADE:
            return item[1]
    dados = (baixar or _baixar)(z, x, y)
    with _trava:
        _cache[chave] = (time.time(), dados)
        _cache.move_to_end(chave)
        while len(_cache) > MAX_ITENS:
            _cache.popitem(last=False)
    return dados


def limpar_cache() -> None:
    with _trava:
        _cache.clear()
