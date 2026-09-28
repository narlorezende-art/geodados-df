"""Tráfego aéreo sobre o DF (ADS-B), no espírito do God's Eye View.

Fonte principal: adsb.lol (rede comunitária de ADS-B, aberta, sem chave).
Reserva: OpenSky Network (anônimo, ou com OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET).
O resultado fica 10 s em cache para respeitar os limites das fontes.

Aeronaves de órgãos (DETRAN-DF, PMDF, CBMDF…) são reconhecidas pela variável
FROTA, no formato "PR-ABC:PMDF;PT-XYZ:CBMDF;E4812A:DETRAN" (matrícula ou código hex).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

CENTRO = (-15.79, -47.88)       # Brasília
RAIO_NM = 60                    # ~110 km: DF e entorno
BBOX = (-16.35, -48.55, -15.20, -47.20)   # lat_min, lon_min, lat_max, lon_max (OpenSky)
VALIDADE = 10                   # segundos
UA = {"User-Agent": "CCOTRAN-DF/1.0 (painel privado)"}

# Designadores ICAO de helicópteros comuns no Brasil (reforça a categoria A7 do ADS-B)
HELICOPTEROS = {
    "AS50", "AS55", "AS65", "AS32", "AS3B", "EC20", "EC25", "EC30", "EC35", "EC45", "EC55", "EC75",
    "H160", "H175", "B06", "B06T", "B407", "B412", "B427", "B429", "B505", "BK17", "R22", "R44", "R66",
    "S76", "S92", "A109", "A119", "A139", "A169", "A189", "AW09", "H60", "UH1", "H500", "MD52", "MD60",
    "EN28", "EN48", "S300", "G2CA", "BO05", "B222", "B230", "B47G", "PUMA", "LYNX", "NH90",
}

_trava = threading.Lock()
_cache: dict = {"quando": 0.0, "dados": None}
_token: dict = {"valor": None, "expira": 0.0}


def frota(bruto: str | None = None) -> dict[str, str]:
    """Mapa matrícula/hex (normalizados) → órgão."""
    bruto = os.environ.get("FROTA", "") if bruto is None else bruto
    saida = {}
    for parte in bruto.replace("\n", ";").split(";"):
        chave, sep, orgao = parte.strip().partition(":")
        if sep and chave.strip() and orgao.strip():
            saida[_norm(chave)] = orgao.strip().upper()
    return saida


def _norm(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _get_json(url: str, headers: dict | None = None, timeout: int = 12):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# ---------------- fontes ----------------

def _adsblol() -> list[dict]:
    lat, lon = CENTRO
    dados = _get_json(f"https://api.adsb.lol/v2/point/{lat}/{lon}/{RAIO_NM}")
    saida = []
    for a in dados.get("ac") or []:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        alt = a.get("alt_geom", a.get("alt_baro"))
        no_chao = alt == "ground"
        alt_m = 0.0 if no_chao or not isinstance(alt, (int, float)) else alt * 0.3048
        saida.append({
            "hex": (a.get("hex") or "").lower(),
            "voo": (a.get("flight") or "").strip(),
            "reg": (a.get("r") or "").strip(),
            "tipo": (a.get("t") or "").strip().upper(),
            "cat": (a.get("category") or "").upper(),
            "lat": a["lat"], "lon": a["lon"], "alt": round(alt_m),
            "vel": round((a.get("gs") or 0) * 1.852),           # nós → km/h
            "rumo": a.get("track") or a.get("true_heading") or 0,
            "chao": no_chao,
            "idade": a.get("seen_pos", a.get("seen", 0)) or 0,
        })
    return saida


def _opensky_token() -> str | None:
    cid, seg = os.environ.get("OPENSKY_CLIENT_ID"), os.environ.get("OPENSKY_CLIENT_SECRET")
    if not cid or not seg:
        return None
    if _token["valor"] and time.time() < _token["expira"] - 60:
        return _token["valor"]
    corpo = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": seg}).encode()
    req = urllib.request.Request(
        "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token",
        data=corpo, headers={**UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        t = json.load(resp)
    _token.update(valor=t["access_token"], expira=time.time() + int(t.get("expires_in", 1800)))
    return _token["valor"]


# categoria numérica do OpenSky → código ADS-B (8 = helicóptero)
_OS_CAT = {2: "A1", 3: "A2", 4: "A3", 5: "A4", 6: "A5", 7: "A6", 8: "A7", 9: "B1", 10: "B2", 11: "B3", 12: "B4", 14: "B6"}


def _opensky() -> list[dict]:
    la0, lo0, la1, lo1 = BBOX
    url = f"https://opensky-network.org/api/states/all?lamin={la0}&lomin={lo0}&lamax={la1}&lomax={lo1}&extended=1"
    tok = _opensky_token()
    dados = _get_json(url, {"Authorization": f"Bearer {tok}"} if tok else None)
    agora = dados.get("time") or time.time()
    saida = []
    for s in dados.get("states") or []:
        if s[5] is None or s[6] is None:
            continue
        alt = s[13] if s[13] is not None else s[7]
        saida.append({
            "hex": (s[0] or "").lower(), "voo": (s[1] or "").strip(), "reg": "", "tipo": "",
            "cat": _OS_CAT.get(s[17] if len(s) > 17 else None, ""),
            "lat": s[6], "lon": s[5], "alt": round(alt or 0),
            "vel": round((s[9] or 0) * 3.6), "rumo": s[10] or 0, "chao": bool(s[8]),
            "idade": max(0, agora - (s[3] or agora)),
        })
    return saida


FONTES = [("adsb.lol", _adsblol), ("OpenSky Network", _opensky)]


def _classificar(lista: list[dict], mapa_frota: dict[str, str]) -> list[dict]:
    for a in lista:
        a["heli"] = a["cat"] == "A7" or a["tipo"] in HELICOPTEROS
        a["orgao"] = mapa_frota.get(_norm(a["reg"])) or mapa_frota.get(_norm(a["hex"])) or ""
    return lista


def aeronaves(fontes=None) -> dict:
    """Aeronaves no DF e entorno, com cache de 10 s e troca automática de fonte."""
    with _trava:
        agora = time.time()
        if _cache["dados"] and agora - _cache["quando"] < VALIDADE:
            return _cache["dados"]
        erros = []
        for nome, buscar in (fontes or FONTES):
            try:
                lista = _classificar(buscar(), frota())
                dados = {"fonte": nome, "hora": int(agora), "aeronaves": lista}
                _cache.update(quando=agora, dados=dados)
                return dados
            except Exception as e:  # tenta a próxima fonte
                erros.append(f"{nome}: {e.__class__.__name__}")
        if _cache["dados"]:
            return {**_cache["dados"], "desatualizado": True}
        raise RuntimeError("Tráfego aéreo indisponível no momento (" + "; ".join(erros) + ").")


def limpar_cache() -> None:
    _cache.update(quando=0.0, dados=None)
