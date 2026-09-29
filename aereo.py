"""Tráfego aéreo sobre o DF (ADS-B), no espírito do God's Eye View.

Consulta VÁRIAS redes ao mesmo tempo e junta o resultado pelo código ICAO (hex) de
cada aeronave — cada rede tem antenas diferentes, e juntas enxergam mais:
  • adsb.lol  (comunitária, aberta, sem chave)
  • adsb.fi   (comunitária, aberta, sem chave; uso não comercial, citar adsb.fi)
  • OpenSky Network (anônimo tem cota diária pequena, então é consultado a cada 5 min;
    com OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET, a cada 30 s)
Para cada aeronave vale a posição mais recente entre as redes. Resultado em cache por 10 s.

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
from concurrent.futures import ThreadPoolExecutor

CENTRO = (-15.79, -47.88)       # Brasília
RAIO_NM = 60                    # ~110 km: DF e entorno
BBOX = (-16.35, -48.55, -15.20, -47.20)   # lat_min, lon_min, lat_max, lon_max (OpenSky)
VALIDADE = 10                   # segundos
UA = {"User-Agent": "CCOMaps/1.0 (painel privado)"}

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

def _readsb(dados: dict) -> list[dict]:
    """Converte o formato readsb (usado por adsb.lol e adsb.fi)."""
    saida = []
    for a in dados.get("ac") or dados.get("aircraft") or []:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        alt = a.get("alt_geom", a.get("alt_baro"))
        no_chao = alt == "ground"
        alt_m = 0.0 if no_chao or not isinstance(alt, (int, float)) else alt * 0.3048
        saida.append({
            "hex": (a.get("hex") or "").lower().lstrip("~"),
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


def _adsblol() -> list[dict]:
    lat, lon = CENTRO
    return _readsb(_get_json(f"https://api.adsb.lol/v2/point/{lat}/{lon}/{RAIO_NM}"))


def _adsbfi() -> list[dict]:
    lat, lon = CENTRO
    return _readsb(_get_json(f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{RAIO_NM}"))


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


FONTES = [("adsb.lol", _adsblol), ("adsb.fi", _adsbfi), ("OpenSky", _opensky)]
IDADE_MAX = 120          # s: posição mais velha que isso é descartada


def _intervalo(nome: str) -> int:
    """De quanto em quanto tempo cada rede pode ser consultada."""
    if nome == "OpenSky":
        return 30 if os.environ.get("OPENSKY_CLIENT_ID") else 300
    return VALIDADE


_por_fonte: dict = {}    # nome -> {"quando": t, "lista": [...], "pausa_ate": t, "erro": str}


def _classificar(lista: list[dict], mapa_frota: dict[str, str]) -> list[dict]:
    for a in lista:
        a["heli"] = a["cat"] == "A7" or a["tipo"] in HELICOPTEROS
        a["orgao"] = mapa_frota.get(_norm(a["reg"])) or mapa_frota.get(_norm(a["hex"])) or ""
    return lista


def juntar(listas: list[list[dict]]) -> list[dict]:
    """Uma entrada por aeronave: posição mais recente; completa matrícula/tipo/voo com as outras redes."""
    melhor: dict[str, dict] = {}
    for lista in listas:
        for a in lista:
            if not a.get("hex") or a.get("idade", 0) > IDADE_MAX:
                continue
            atual = melhor.get(a["hex"])
            if atual is None:
                melhor[a["hex"]] = dict(a)
                continue
            novo, velho = (a, atual) if a.get("idade", 0) < atual.get("idade", 0) else (atual, a)
            combinado = dict(novo)
            for campo in ("reg", "tipo", "voo", "cat"):
                if not combinado.get(campo) and velho.get(campo):
                    combinado[campo] = velho[campo]
            melhor[a["hex"]] = combinado
    return list(melhor.values())


def _consultar(nome, buscar, agora):
    """Consulta uma rede respeitando o intervalo dela; devolve a lista (com idade atualizada) ou None."""
    info = _por_fonte.setdefault(nome, {"quando": 0.0, "lista": None, "pausa_ate": 0.0, "erro": ""})
    if agora < info["pausa_ate"]:
        pass
    elif agora - info["quando"] >= _intervalo(nome) or info["lista"] is None:
        try:
            info["lista"] = buscar()
            info["quando"] = agora
            info["erro"] = ""
        except Exception as e:
            codigo = getattr(e, "code", None)
            motivo = getattr(e, "reason", "") or str(e)[:80]
            info["erro"] = f"{e.__class__.__name__} {codigo or ''} {motivo}".strip()
            info["pausa_ate"] = agora + (600 if codigo in (401, 403, 429) else 30)   # cota estourada: descansa
    if info["lista"] is None:
        return None
    passou = agora - info["quando"]
    return [{**a, "idade": (a.get("idade") or 0) + passou} for a in info["lista"]]


def aeronaves(fontes=None) -> dict:
    """Aeronaves no DF e entorno, somando as redes disponíveis. Cache de 10 s."""
    with _trava:
        agora = time.time()
        if _cache["dados"] and agora - _cache["quando"] < VALIDADE:
            return _cache["dados"]
        fontes = fontes or FONTES
        with ThreadPoolExecutor(max_workers=len(fontes)) as ex:
            resultados = list(ex.map(lambda f: (f[0], _consultar(f[0], f[1], agora)), fontes))
        ok = [(n, l) for n, l in resultados if l is not None]
        if ok:
            lista = _classificar(juntar([l for _, l in ok]), frota())
            dados = {
                "fonte": " + ".join(n for n, _ in ok), "hora": int(agora), "aeronaves": lista,
                "por_fonte": {n: (len(l) if l is not None else _por_fonte.get(n, {}).get("erro") or "sem dados") for n, l in resultados},
            }
            _cache.update(quando=agora, dados=dados)
            return dados
        if _cache["dados"]:
            return {**_cache["dados"], "desatualizado": True}
        erros = "; ".join(f"{n}: {_por_fonte.get(n, {}).get('erro') or 'sem resposta'}" for n, _ in resultados)
        raise RuntimeError("Tráfego aéreo indisponível no momento (" + erros + ").")


def limpar_cache() -> None:
    _cache.update(quando=0.0, dados=None)
    _por_fonte.clear()
