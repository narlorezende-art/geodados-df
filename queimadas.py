"""Focos de queimada (focos de calor por satélite) no DF e entorno — INPE, dados abertos.

Lê os arquivos diários do Programa Queimadas (hoje e ontem, horário UTC), filtra a região
do DF com folga e as últimas 48 h, e guarda o resultado 30 minutos em cache.
Fonte: https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/
"""
from __future__ import annotations

import csv
import io
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/focos_diario_br_{data}.csv"
REGIAO = (-16.60, -48.90, -15.00, -46.80)   # lat_min, lon_min, lat_max, lon_max (DF + entorno)
JANELA_H = 48
VALIDADE = 30 * 60

_trava = threading.Lock()
_cache: dict = {"quando": 0.0, "dados": None}


def _baixar(data: str) -> str:
    req = urllib.request.Request(URL.format(data=data), headers={"User-Agent": "CCOMaps/1.0 (painel privado)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _achar(cab: list[str], *nomes: str) -> int | None:
    baixa = [c.strip().lower() for c in cab]
    for n in nomes:
        if n in baixa:
            return baixa.index(n)
    return None


def _quando(txt: str) -> datetime | None:
    txt = txt.strip().replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(txt[:19] if fmt.endswith("%S") else txt[:16], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def ler(texto: str, agora: datetime) -> list[dict]:
    """Focos do CSV dentro da região e da janela de tempo."""
    leitor = csv.reader(io.StringIO(texto))
    cab = next(leitor, None)
    if not cab:
        return []
    i_lat, i_lon = _achar(cab, "lat", "latitude"), _achar(cab, "lon", "longitude")
    i_t = _achar(cab, "data_hora_gmt", "datahora", "data_pas", "data")
    i_sat, i_mun, i_uf, i_frp = _achar(cab, "satelite"), _achar(cab, "municipio"), _achar(cab, "estado"), _achar(cab, "frp")
    if i_lat is None or i_lon is None or i_t is None:
        raise ValueError("Formato do arquivo do INPE mudou (colunas lat/lon/data não encontradas).")
    la0, lo0, la1, lo1 = REGIAO
    limite = agora - timedelta(hours=JANELA_H)
    saida = []
    for linha in leitor:
        try:
            lat, lon = float(linha[i_lat]), float(linha[i_lon])
        except (ValueError, IndexError):
            continue
        if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
            continue
        t = _quando(linha[i_t])
        if not t or t < limite or t > agora + timedelta(hours=1):
            continue
        pega = lambda i: linha[i].strip() if i is not None and i < len(linha) else ""  # noqa: E731
        frp = pega(i_frp)
        saida.append({
            "lat": round(lat, 5), "lon": round(lon, 5),
            "hora": t.isoformat(timespec="minutes"),
            "horas": round((agora - t).total_seconds() / 3600, 1),
            "sat": pega(i_sat), "mun": pega(i_mun).title(), "uf": pega(i_uf).title(),
            "frp": float(frp) if frp.replace(".", "", 1).isdigit() else None,
        })
    return saida


def focos(baixar=None, agora: datetime | None = None) -> dict:
    with _trava:
        if _cache["dados"] and time.time() - _cache["quando"] < VALIDADE and agora is None:
            return _cache["dados"]
        agora = agora or datetime.now(timezone.utc)
        dias = [(agora - timedelta(days=d)).strftime("%Y%m%d") for d in (0, 1, 2)]
        pontos, lidos = {}, 0
        for dia in dias:
            try:
                texto = (baixar or _baixar)(dia)
            except Exception:
                continue     # o arquivo de hoje pode ainda não existir
            lidos += 1
            for f in ler(texto, agora):
                pontos[(f["lat"], f["lon"], f["hora"])] = f      # remove repetidos entre arquivos
        if not lidos:
            if _cache["dados"]:
                return {**_cache["dados"], "desatualizado": True}
            raise RuntimeError("Focos de queimada indisponíveis no momento (INPE não respondeu).")
        lista = sorted(pontos.values(), key=lambda f: f["horas"])
        dados = {"fonte": "INPE — Programa Queimadas", "atualizado": agora.isoformat(timespec="minutes"),
                 "janela_h": JANELA_H, "focos": lista}
        _cache.update(quando=time.time(), dados=dados)
        return dados


def limpar_cache() -> None:
    _cache.update(quando=0.0, dados=None)
