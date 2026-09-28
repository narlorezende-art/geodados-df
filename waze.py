"""Waze for Cities (Waze Data Feed) — alertas e congestionamentos em tempo real.

A URL do feed é secreta e fica só no servidor, na variável WAZE_FEED_URL
(Partner Hub → Toolbox → Waze Data Feed). O Waze atualiza o feed a cada 2 minutos;
aqui ele fica 2 minutos em cache, e o navegador recebe só os dados já organizados.
Atribuição obrigatória: "Dados: Waze".
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

VALIDADE = 120
_trava = threading.Lock()
_cache: dict = {"quando": 0.0, "dados": None}

# categorias exibidas no painel
CATEGORIAS = {
    "acidente": "Acidentes",
    "alagamento": "Alagamentos",
    "clima": "Clima na via",
    "perigo": "Perigos na via",
    "interdicao": "Interdições e obras",
    "policia": "Polícia",
    "outro": "Outros alertas",
}

SUBTIPOS = {
    "ACCIDENT_MINOR": "Acidente leve", "ACCIDENT_MAJOR": "Acidente grave",
    "HAZARD_WEATHER_FLOOD": "Alagamento", "HAZARD_WEATHER_MONSOON": "Chuva torrencial",
    "HAZARD_WEATHER_HEAVY_RAIN": "Chuva forte", "HAZARD_WEATHER_FOG": "Neblina", "HAZARD_WEATHER_HAIL": "Granizo",
    "HAZARD_WEATHER_HEAT_WAVE": "Onda de calor", "HAZARD_WEATHER": "Condição climática",
    "HAZARD_ON_ROAD": "Perigo na via", "HAZARD_ON_ROAD_OBJECT": "Objeto na via", "HAZARD_ON_ROAD_POT_HOLE": "Buraco",
    "HAZARD_ON_ROAD_ROAD_KILL": "Animal morto na via", "HAZARD_ON_ROAD_CAR_STOPPED": "Veículo parado na via",
    "HAZARD_ON_ROAD_OIL": "Óleo na pista", "HAZARD_ON_ROAD_ICE": "Gelo na pista",
    "HAZARD_ON_ROAD_TRAFFIC_LIGHT_FAULT": "Semáforo com defeito", "HAZARD_ON_ROAD_LANE_CLOSED": "Faixa interditada",
    "HAZARD_ON_ROAD_CONSTRUCTION": "Obra na via", "HAZARD_ON_ROAD_EMERGENCY_VEHICLE": "Veículo de emergência",
    "HAZARD_ON_SHOULDER": "Perigo no acostamento", "HAZARD_ON_SHOULDER_CAR_STOPPED": "Veículo no acostamento",
    "HAZARD_ON_SHOULDER_ANIMALS": "Animais no acostamento", "HAZARD_ON_SHOULDER_MISSING_SIGN": "Placa faltando",
    "ROAD_CLOSED_HAZARD": "Via fechada (perigo)", "ROAD_CLOSED_CONSTRUCTION": "Via fechada (obra)",
    "ROAD_CLOSED_EVENT": "Via fechada (evento)", "POLICE_VISIBLE": "Polícia visível", "POLICE_HIDING": "Polícia",
    "JAM_STAND_STILL_TRAFFIC": "Trânsito parado", "JAM_HEAVY_TRAFFIC": "Trânsito intenso",
    "JAM_MODERATE_TRAFFIC": "Trânsito moderado", "JAM_LIGHT_TRAFFIC": "Trânsito leve",
}
TIPOS = {"ACCIDENT": "Acidente", "WEATHERHAZARD": "Perigo", "HAZARD": "Perigo", "ROAD_CLOSED": "Via fechada",
         "CONSTRUCTION": "Obra", "POLICE": "Polícia", "JAM": "Congestionamento", "MISC": "Alerta"}


def ativo() -> bool:
    return bool(os.environ.get("WAZE_FEED_URL", "").strip())


def categoria(tipo: str, sub: str) -> str:
    tipo, sub = (tipo or "").upper(), (sub or "").upper()
    if tipo == "ACCIDENT":
        return "acidente"
    if sub in ("HAZARD_WEATHER_FLOOD", "HAZARD_WEATHER_MONSOON"):
        return "alagamento"
    if sub.startswith("HAZARD_WEATHER"):
        return "clima"
    if tipo in ("ROAD_CLOSED", "CONSTRUCTION") or sub in ("HAZARD_ON_ROAD_CONSTRUCTION", "HAZARD_ON_ROAD_LANE_CLOSED"):
        return "interdicao"
    if tipo in ("WEATHERHAZARD", "HAZARD") or sub.startswith("HAZARD_"):
        return "perigo"
    if tipo == "POLICE":
        return "policia"
    return "outro"


def _baixar() -> dict:
    url = os.environ["WAZE_FEED_URL"].strip()
    partes = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(partes.query))
    q.setdefault("format", "1")
    q["types"] = "alerts,traffic"
    url = urllib.parse.urlunsplit(partes._replace(query=urllib.parse.urlencode(q)))
    req = urllib.request.Request(url, headers={"User-Agent": "CCOMaps/1.0 (painel privado)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def organizar(bruto: dict) -> dict:
    alertas = []
    for a in bruto.get("alerts") or []:
        loc = a.get("location") or {}
        if loc.get("x") is None or loc.get("y") is None:
            continue
        tipo, sub = a.get("type", ""), a.get("subtype", "")
        if (tipo or "").upper() == "JAM":
            continue                          # congestionamento já vem como linha em "jams"
        alertas.append({
            "id": a.get("uuid"), "cat": categoria(tipo, sub),
            "rotulo": SUBTIPOS.get((sub or "").upper()) or TIPOS.get((tipo or "").upper(), "Alerta"),
            "lat": loc["y"], "lon": loc["x"], "rua": a.get("street") or "", "cidade": a.get("city") or "",
            "conf": a.get("confidence"), "rel": a.get("reliability"), "likes": a.get("nThumbsUp") or 0,
            "quando": a.get("pubMillis"), "desc": (a.get("reportDescription") or "")[:200],
        })
    congest = []
    for j in bruto.get("jams") or []:
        linha = [[p["x"], p["y"]] for p in (j.get("line") or []) if "x" in p and "y" in p]
        if len(linha) < 2:
            continue
        congest.append({
            "id": j.get("uuid"), "nivel": j.get("level", 0), "linha": linha,
            "vel": round(j.get("speedKMH") or (j.get("speed") or 0) * 3.6), "atraso": j.get("delay") or 0,
            "comp": j.get("length") or 0, "rua": j.get("street") or "", "cidade": j.get("city") or "",
            "quando": j.get("pubMillis"),
        })
    return {"fonte": "Waze", "atualizado": int(time.time()), "categorias": CATEGORIAS,
            "alertas": alertas, "congestionamentos": congest}


def dados(baixar=None) -> dict:
    if not ativo():
        raise PermissionError("Configure WAZE_FEED_URL no Render para ativar o Waze.")
    with _trava:
        if _cache["dados"] and time.time() - _cache["quando"] < VALIDADE:
            return _cache["dados"]
        try:
            d = organizar((baixar or _baixar)())
        except Exception as erro:
            if _cache["dados"]:
                return {**_cache["dados"], "desatualizado": True}
            raise RuntimeError(f"Feed do Waze indisponível no momento ({erro.__class__.__name__}).") from erro
        _cache.update(quando=time.time(), dados=d)
        return d


def limpar_cache() -> None:
    _cache.update(quando=0.0, dados=None)
