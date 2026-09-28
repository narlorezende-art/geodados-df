"""Previsão do tempo sobre o DF (Open-Meteo), para as camadas Chuva e Temperatura.

Busca uma grade de pontos cobrindo o Distrito Federal, com previsão hora a hora
para as próximas 48 h, e guarda em memória por 1 hora. Gratuito e sem chave
para uso não comercial (https://open-meteo.com).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Retângulo do DF com folga (lon_min, lat_min, lon_max, lat_max)
BBOX = (-48.32, -16.08, -47.28, -15.46)
NX, NY = 12, 8          # 96 pontos, espaçamento de ~9 km
HORAS = 48
VALIDADE = 60 * 60      # segundos em cache
URL = "https://api.open-meteo.com/v1/forecast"

_trava = threading.Lock()
_cache: dict = {"quando": 0.0, "dados": None}


def grade() -> list[tuple[float, float]]:
    """Pontos (lat, lon) do norte para o sul, e do oeste para o leste em cada linha."""
    lon0, lat0, lon1, lat1 = BBOX
    pontos = []
    for j in range(NY):
        lat = lat1 - (lat1 - lat0) * j / (NY - 1)
        for i in range(NX):
            lon = lon0 + (lon1 - lon0) * i / (NX - 1)
            pontos.append((round(lat, 4), round(lon, 4)))
    return pontos


def _baixar() -> list[dict]:
    pontos = grade()
    params = {
        "latitude": ",".join(str(p[0]) for p in pontos),
        "longitude": ",".join(str(p[1]) for p in pontos),
        "hourly": "temperature_2m,precipitation,precipitation_probability",
        "forecast_hours": HORAS,
        "timezone": "America/Sao_Paulo",
    }
    req = urllib.request.Request(
        URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "CCOMaps/1.0 (painel privado)"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        corpo = json.load(resp)
    return corpo if isinstance(corpo, list) else [corpo]


def _montar(locais: list[dict]) -> dict:
    if len(locais) != NX * NY:
        raise ValueError(f"Open-Meteo devolveu {len(locais)} pontos, esperados {NX * NY}")
    horas = locais[0]["hourly"]["time"]

    def matriz(chave: str, casas: int) -> list[list]:
        saida = []
        for t in range(len(horas)):
            linha = []
            for loc in locais:
                v = loc["hourly"][chave][t]
                linha.append(None if v is None else round(float(v), casas))
            saida.append(linha)
        return saida

    return {
        "fonte": "Open-Meteo",
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": list(BBOX),
        "nx": NX,
        "ny": NY,
        "horas": horas,  # horário de Brasília, ex.: "2026-09-27T15:00"
        "temp": matriz("temperature_2m", 1),            # °C
        "chuva": matriz("precipitation", 1),            # mm na hora
        "prob": matriz("precipitation_probability", 0),  # %
    }


def previsao(baixar=_baixar) -> dict:
    """Previsão em cache. Se a fonte falhar, devolve a última previsão marcada como desatualizada."""
    with _trava:
        agora = time.time()
        if _cache["dados"] and agora - _cache["quando"] < VALIDADE:
            return _cache["dados"]
        try:
            dados = _montar(baixar())
        except Exception as erro:  # rede, limite de uso, formato
            if _cache["dados"]:
                return {**_cache["dados"], "desatualizado": True}
            raise RuntimeError(f"Previsão indisponível no momento ({erro.__class__.__name__}).") from erro
        _cache.update(quando=agora, dados=dados)
        return dados


def limpar_cache() -> None:
    _cache.update(quando=0.0, dados=None)
