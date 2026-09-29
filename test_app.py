"""Testes: rode com  pytest -q"""
import os

os.environ["SESSION_SECRET"] = "segredo-de-teste"

import seguranca  # noqa: E402

os.environ["USERS"] = f"narlo:{seguranca.gerar_hash('senha-correta-123', 1000)};visitante:texto-puro"

from fastapi.testclient import TestClient  # noqa: E402

import dados  # noqa: E402
import main  # noqa: E402

HTML = {"Accept": "text/html"}


def cliente():
    main._falhas.clear()
    return TestClient(main.app, follow_redirects=False)


def entrar(c, u="narlo", s="senha-correta-123", **extra):
    return c.post("/login", data={"usuario": u, "senha": s, **extra})


def test_sem_login_nada_e_entregue():
    c = cliente()
    r = c.get("/", headers=HTML)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    for caminho in ["/data/equipamentos.json", "/app.js", "/app.css", "/api/config", "/index.html"]:
        assert c.get(caminho).status_code == 401, caminho


def test_rotas_livres():
    c = cliente()
    assert c.get("/login").status_code == 200
    assert c.get("/saude").text == "ok"
    assert "Disallow" in c.get("/robots.txt").text


def test_senha_errada_e_usuario_inexistente():
    c = cliente()
    assert "erro=1" in entrar(c, s="errada").headers["location"]
    assert "erro=1" in entrar(c, u="ninguem").headers["location"]


def test_login_ok_libera_dados():
    c = cliente()
    r = entrar(c, u="NARLO")
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "httponly" in r.headers["set-cookie"].lower()
    lista = c.get("/data/equipamentos.json").json()
    assert len(lista) == 407
    assert c.get("/api/me").json() == {"user": "narlo"}
    assert c.get("/").status_code == 200
    assert c.get("/app.js").status_code == 200


def test_senha_em_texto_puro_tambem_funciona():
    c = cliente()
    assert entrar(c, u="visitante", s="texto-puro").headers["location"] == "/"


def test_cookie_adulterado_e_recusado():
    c = cliente()
    entrar(c)
    token = c.cookies.get("gd_session")
    c.cookies.set("gd_session", token[:-2] + "xx")
    assert c.get("/data/equipamentos.json").status_code == 401


def test_usuario_removido_perde_acesso():
    c = cliente()
    entrar(c)
    antigo = os.environ["USERS"]
    os.environ["USERS"] = "outra:pessoa"
    try:
        assert c.get("/data/equipamentos.json").status_code == 401
    finally:
        os.environ["USERS"] = antigo


def test_nao_redireciona_para_outro_site():
    c = cliente()
    assert entrar(c, next="//site-malicioso.com").headers["location"] == "/"
    assert entrar(c, next="/?ra=1").headers["location"] == "/?ra=1"


def test_limite_de_tentativas():
    c = cliente()
    for _ in range(main.TENTATIVAS_MAX):
        entrar(c, s="errada")
    assert "erro=limite" in entrar(c).headers["location"]  # até a senha certa é barrada


def test_logout():
    c = cliente()
    entrar(c)
    c.get("/logout")
    c.cookies.clear()
    assert c.get("/data/equipamentos.json").status_code == 401


def test_codigo_e_planilha_nunca_sao_servidos():
    c = cliente()
    entrar(c)
    for arquivo in ["main.py", "seguranca.py", "equipamentos.csv", "render.yaml", "README.md", "requirements.txt"]:
        assert c.get("/" + arquivo).status_code == 404, arquivo
    assert c.get("/app.css").status_code == 200
    assert c.get("/cesium/Cesium.js").status_code in (200, 404)


def test_painel_nunca_fica_preso_em_versao_antiga():
    c = cliente()
    entrar(c)
    for caminho in ["/", "/app.js", "/app.css", "/app.js?v=3"]:
        r = c.get(caminho)
        assert r.status_code == 200 and "no-cache" in r.headers["cache-control"], caminho


def test_logo_so_depois_do_login():
    c = cliente()
    assert c.get("/logo.png").status_code == 401
    assert "logo" not in c.get("/login").text.lower()
    entrar(c)
    r = c.get("/logo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_cabecalhos_de_seguranca():
    c = cliente()
    r = c.get("/login")
    assert r.headers["x-frame-options"] == "DENY"
    # só o domínio vai para outros sites (o OpenStreetMap bloqueia pedidos sem essa informação)
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "noindex" in r.headers["x-robots-tag"]


def test_dados_limpos():
    itens = dados.equipamentos()
    assert {i["t"] for i in itens} == {"CE", "RE", "NM"}
    assert sum(i["t"] == "CE" for i in itens) == 149
    assert sum(i["t"] == "RE" for i in itens) == 124
    assert sum(i["t"] == "NM" for i in itens) == 134
    assert len({i["cra"] for i in itens}) == 20
    assert not any("ÿ" in i["end"] or i["end"].endswith("<") for i in itens)
    assert all(-16.1 < i["lat"] < -15.5 and -48.3 < i["lon"] < -47.5 for i in itens)


# ---------------- clima ----------------
import clima  # noqa: E402


def _locais_falsos():
    horas = [f"2026-09-27T{h:02d}:00" for h in range(48)]
    return [{"hourly": {"time": horas,
                        "temperature_2m": [20.0 + k * 0.1 + h * 0.01 for h in range(48)],
                        "precipitation": [0.0 if k % 3 else 1.24 for _ in range(48)],
                        "precipitation_probability": [k % 100 for _ in range(48)]}}
            for k in range(clima.NX * clima.NY)]


def test_grade_cobre_o_df():
    pts = clima.grade()
    assert len(pts) == clima.NX * clima.NY
    assert pts[0][0] > pts[-1][0]  # começa no norte
    assert min(p[1] for p in pts) < -48.2 and max(p[1] for p in pts) > -47.35


def test_previsao_monta_matrizes_e_usa_cache():
    clima.limpar_cache()
    chamadas = []
    fonte = lambda: chamadas.append(1) or _locais_falsos()  # noqa: E731
    d = clima.previsao(fonte)
    assert len(d["horas"]) == 48 and len(d["temp"]) == 48 and len(d["temp"][0]) == 96
    assert d["chuva"][0][0] == 1.2 and d["prob"][0][5] == 5
    clima.previsao(fonte)
    assert len(chamadas) == 1  # segunda chamada veio do cache


def test_previsao_falha_devolve_ultima_ou_erro():
    clima.limpar_cache()
    def quebrada():
        raise OSError("sem rede")
    try:
        clima.previsao(quebrada)
        assert False, "deveria falhar sem cache"
    except RuntimeError:
        pass
    clima.previsao(_locais_falsos)
    clima._cache["quando"] = 0  # força expirar
    assert clima.previsao(quebrada)["desatualizado"] is True
    clima.limpar_cache()


def test_api_clima_exige_login_e_responde():
    clima.limpar_cache()
    clima.previsao(_locais_falsos)
    c = cliente()
    assert c.get("/api/clima").status_code == 401
    entrar(c)
    r = c.get("/api/clima")
    assert r.status_code == 200 and r.json()["nx"] == clima.NX
    clima.limpar_cache()


# ---------------- fotos aéreas do GDF ----------------
import gdf  # noqa: E402

BRASILIA_Z12 = (12, 1502, 2229)


def test_bbox_e_recorte_do_df():
    xmin, ymin, xmax, ymax = gdf.bbox_do_bloco(0, 0, 0)
    assert round(xmin) == -20037508 and round(ymax) == 20037508
    assert gdf.bloco_no_df(*BRASILIA_Z12)
    assert not gdf.bloco_no_df(12, 1502 + 60, 2229)


def test_bloco_valida_camada_e_usa_cache():
    gdf.limpar_cache()
    chamadas = []
    def falso(s, z, x, y):
        chamadas.append((s, z, x, y))
        return b"\xff\xd8img", "image/jpeg"
    assert gdf.bloco("FOTO_AEREA_2024", *BRASILIA_Z12, baixar=falso)[1] == "image/jpeg"
    gdf.bloco("FOTO_AEREA_2024", *BRASILIA_Z12, baixar=falso)
    assert len(chamadas) == 1
    assert gdf.bloco("FOTO_1964", 12, 1502 + 60, 2229, baixar=falso) == (gdf.VAZIO, "image/png")  # fora do DF
    assert gdf.bloco("FOTO_1964", 7, 46, 69, baixar=falso) == (gdf.VAZIO, "image/png")  # zoom muito afastado
    for ruim in [("OUTRA", *BRASILIA_Z12), ("FOTO_1964", 30, 0, 0), ("FOTO_1964", 12, -1, 0)]:
        try:
            gdf.bloco(*ruim, baixar=falso)
            assert False, ruim
        except ValueError:
            pass
    gdf.limpar_cache()


def test_rota_gdf_exige_login_e_guarda_no_navegador(monkeypatch):
    gdf.limpar_cache()
    monkeypatch.setattr(gdf, "_baixar", lambda s, z, x, y: (b"\xff\xd8img", "image/jpeg"))
    c = cliente()
    assert c.get("/gdf/FOTO_AEREA_2024/12/1502/2229").status_code == 401
    entrar(c)
    r = c.get("/gdf/FOTO_AEREA_2024/12/1502/2229")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "max-age=604800" in r.headers["cache-control"]
    assert c.get("/gdf/NAO_EXISTE/12/1502/2229").status_code == 400
    assert len(c.get("/api/config").json()["gdf"]) == len(gdf.SERVICOS)
    gdf.limpar_cache()


def test_rota_gdf_falha_com_502(monkeypatch):
    gdf.limpar_cache()
    def quebra(*a):
        raise OSError("fora do ar")
    monkeypatch.setattr(gdf, "_baixar", quebra)
    c = cliente()
    entrar(c)
    assert c.get("/gdf/FOTO_2009/12/1502/2229").status_code == 502


# ---------------- tráfego aéreo ----------------
import aereo  # noqa: E402


def test_frota_e_classificacao():
    mapa = aereo.frota("PR-ABC:pmdf; e4812a:DETRAN ;lixo")
    assert mapa == {"PRABC": "PMDF", "E4812A": "DETRAN"}
    lista = aereo._classificar([
        {"hex": "e4812a", "reg": "", "tipo": "AS50", "cat": ""},
        {"hex": "abc", "reg": "PR-ABC", "tipo": "", "cat": "A7"},
        {"hex": "xyz", "reg": "PR-GOL", "tipo": "B738", "cat": "A3"},
    ], mapa)
    assert [a["heli"] for a in lista] == [True, True, False]
    assert [a["orgao"] for a in lista] == ["DETRAN", "PMDF", ""]


def test_aeronaves_troca_de_fonte_e_cache():
    aereo.limpar_cache()
    chamadas = []
    def quebrada():
        chamadas.append("a"); raise OSError("fora")
    def boa():
        chamadas.append("b")
        return [{"hex": "1", "voo": "X", "reg": "", "tipo": "", "cat": "A7", "lat": -15.8, "lon": -47.9,
                 "alt": 300, "vel": 180, "rumo": 90, "chao": False, "idade": 1}]
    d = aereo.aeronaves([("A", quebrada), ("B", boa)])
    assert d["fonte"] == "B" and d["aeronaves"][0]["heli"] is True
    aereo.aeronaves([("A", quebrada), ("B", boa)])
    assert chamadas == ["a", "b"]           # segunda vez veio do cache
    aereo._cache["quando"] = 0
    assert aereo.aeronaves([("A", quebrada)])["desatualizado"] is True
    aereo.limpar_cache()
    try:
        aereo.aeronaves([("A", quebrada)])
        assert False
    except RuntimeError:
        pass


def test_adsblol_converte_campos(monkeypatch):
    monkeypatch.setattr(aereo, "_get_json", lambda url, h=None: {"ac": [
        {"hex": "E4812A", "flight": "PMDF01 ", "r": "PR-ABC", "t": "AS50", "category": "A7",
         "lat": -15.8, "lon": -47.9, "alt_baro": 1000, "gs": 100, "track": 45, "seen_pos": 2},
        {"hex": "aa", "lat": -15.7, "lon": -47.8, "alt_baro": "ground", "gs": 5},
        {"hex": "sem-posicao"},
    ]})
    lista = aereo._adsblol()
    assert len(lista) == 2
    assert lista[0]["alt"] == 305 and lista[0]["vel"] == 185 and lista[0]["voo"] == "PMDF01"
    assert lista[1]["chao"] is True and lista[1]["alt"] == 0


def test_juntar_redes_pega_posicao_mais_recente_e_completa_dados():
    lol = [{"hex": "e4a001", "voo": "", "reg": "", "tipo": "", "cat": "A7", "lat": -15.80, "lon": -47.90, "idade": 8},
           {"hex": "aaa111", "voo": "GLO1", "reg": "PR-GXA", "tipo": "B738", "cat": "A3", "lat": -15.9, "lon": -47.9, "idade": 2}]
    fi = [{"hex": "e4a001", "voo": "PMDF01", "reg": "PR-PMA", "tipo": "AS50", "cat": "", "lat": -15.81, "lon": -47.91, "idade": 1},
          {"hex": "bbb222", "voo": "", "reg": "", "tipo": "", "cat": "", "lat": -15.7, "lon": -47.8, "idade": 500}]
    junto = {a["hex"]: a for a in aereo.juntar([lol, fi])}
    assert set(junto) == {"e4a001", "aaa111"}                   # posição velha demais é descartada
    h = junto["e4a001"]
    assert (h["lat"], h["voo"], h["reg"], h["tipo"], h["cat"]) == (-15.81, "PMDF01", "PR-PMA", "AS50", "A7")


def test_soma_redes_e_informa_por_fonte():
    aereo.limpar_cache()
    a = lambda: [{"hex": "1", "voo": "", "reg": "", "tipo": "", "cat": "", "lat": -15.8, "lon": -47.9, "alt": 1, "vel": 1, "rumo": 0, "chao": False, "idade": 1}]  # noqa: E731
    b = lambda: [{"hex": "2", "voo": "", "reg": "", "tipo": "", "cat": "", "lat": -15.7, "lon": -47.9, "alt": 1, "vel": 1, "rumo": 0, "chao": False, "idade": 1}]  # noqa: E731
    def c():
        raise OSError("fora")
    d = aereo.aeronaves([("adsb.lol", a), ("adsb.fi", b), ("OpenSky", c)])
    assert d["fonte"] == "adsb.lol + adsb.fi" and len(d["aeronaves"]) == 2
    assert d["por_fonte"]["adsb.lol"] == 1 and d["por_fonte"]["OpenSky"].startswith("OSError")
    aereo.limpar_cache()


def test_opensky_anonimo_consultado_com_menos_frequencia(monkeypatch):
    aereo.limpar_cache()
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    assert aereo._intervalo("OpenSky") == 300 and aereo._intervalo("adsb.lol") == 10
    chamadas = []
    fonte = lambda: chamadas.append(1) or []  # noqa: E731
    aereo._consultar("OpenSky", fonte, 1000.0)
    aereo._consultar("OpenSky", fonte, 1060.0)       # 1 min depois: reaproveita
    aereo._consultar("OpenSky", fonte, 1301.0)       # 5 min depois: consulta de novo
    assert len(chamadas) == 2
    aereo.limpar_cache()


def test_rota_aeronaves(monkeypatch):
    aereo.limpar_cache()
    monkeypatch.setattr(aereo, "FONTES", [("teste", lambda: [])])
    c = cliente()
    assert c.get("/api/aeronaves").status_code == 401
    entrar(c)
    assert c.get("/api/aeronaves").json()["fonte"] == "teste"
    aereo.limpar_cache()


# ---------------- queimadas ----------------
import queimadas  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

CSV_INPE = """id,lat,lon,data_hora_gmt,satelite,municipio,estado,pais,frp
1,-15.80,-47.90,2026-09-28 14:10:00,AQUA_M-T,BRASILIA,DISTRITO FEDERAL,Brasil,12.5
2,-15.90,-48.10,2026-09-25 14:10:00,NPP-375,BRASILIA,DISTRITO FEDERAL,Brasil,
3,-10.00,-50.00,2026-09-28 14:10:00,GOES-19,PALMAS,TOCANTINS,Brasil,3
4,-16.10,-47.50,2026-09-27 20:00:00,NOAA-20,LUZIANIA,GOIAS,Brasil,
"""


def test_queimadas_filtra_regiao_e_tempo():
    agora = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)
    focos = queimadas.ler(CSV_INPE, agora)
    assert [(f["mun"], f["horas"]) for f in focos] == [("Brasilia", 1.8), ("Luziania", 20.0)]
    assert focos[0]["frp"] == 12.5 and focos[1]["frp"] is None


def test_queimadas_junta_dias_e_tolera_arquivo_ausente():
    queimadas.limpar_cache()
    agora = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)
    def baixar(dia):
        if dia == "20260928":
            raise OSError("ainda não publicado")
        return CSV_INPE
    d = queimadas.focos(baixar, agora)
    assert len(d["focos"]) == 2      # mesmo foco em dois arquivos conta uma vez
    queimadas.limpar_cache()


# ---------------- trânsito ----------------
import transito  # noqa: E402


def test_transito_exige_chave_e_usa_cache(monkeypatch):
    transito.limpar_cache()
    monkeypatch.delenv("TOMTOM_KEY", raising=False)
    c = cliente(); entrar(c)
    assert c.get("/api/config").json()["transito"] is False
    assert c.get("/transito/12/1502/2229").status_code == 404
    monkeypatch.setenv("TOMTOM_KEY", "k")
    chamadas = []
    monkeypatch.setattr(transito, "_baixar", lambda z, x, y: chamadas.append(1) or b"png")
    r = c.get("/transito/12/1502/2229")
    assert r.status_code == 200 and "max-age=120" in r.headers["cache-control"]
    c.get("/transito/12/1502/2229")
    assert len(chamadas) == 1
    assert c.get("/transito/3/0/0").content == transito.VAZIO     # longe demais: bloco vazio, sem gastar cota
    assert c.get("/transito/25/0/0").status_code == 400
    transito.limpar_cache()


# ---------------- Waze for Cities ----------------
import waze  # noqa: E402

FEED = {
    "alerts": [
        {"uuid": "a1", "type": "ACCIDENT", "subtype": "ACCIDENT_MAJOR", "location": {"x": -47.9, "y": -15.8}, "street": "Eixo Monumental", "pubMillis": 1, "reliability": 8, "nThumbsUp": 3},
        {"uuid": "a2", "type": "WEATHERHAZARD", "subtype": "HAZARD_WEATHER_FLOOD", "location": {"x": -47.95, "y": -15.83}},
        {"uuid": "a3", "type": "WEATHERHAZARD", "subtype": "HAZARD_ON_ROAD_TRAFFIC_LIGHT_FAULT", "location": {"x": -47.9, "y": -15.7}},
        {"uuid": "a4", "type": "ROAD_CLOSED", "subtype": "ROAD_CLOSED_EVENT", "location": {"x": -47.9, "y": -15.75}},
        {"uuid": "a5", "type": "POLICE", "subtype": "POLICE_VISIBLE", "location": {"x": -47.91, "y": -15.76}},
        {"uuid": "a6", "type": "JAM", "subtype": "JAM_HEAVY_TRAFFIC", "location": {"x": -47.9, "y": -15.7}},
        {"uuid": "a7", "type": "HAZARD", "subtype": "", "location": {}},
    ],
    "jams": [
        {"uuid": "j1", "level": 4, "speedKMH": 8.4, "delay": 320, "length": 1200, "street": "EPTG",
         "line": [{"x": -48.0, "y": -15.85}, {"x": -47.98, "y": -15.84}]},
        {"uuid": "j2", "level": 2, "line": [{"x": -48.0, "y": -15.85}]},
    ],
}


def test_waze_organiza_categorias():
    d = waze.organizar(FEED)
    cats = {a["id"]: (a["cat"], a["rotulo"]) for a in d["alertas"]}
    assert cats == {
        "a1": ("acidente", "Acidente grave"), "a2": ("alagamento", "Alagamento"),
        "a3": ("perigo", "Semáforo com defeito"), "a4": ("interdicao", "Via fechada (evento)"),
        "a5": ("policia", "Polícia visível"),
    }
    assert len(d["congestionamentos"]) == 1
    j = d["congestionamentos"][0]
    assert j["nivel"] == 4 and j["vel"] == 8 and j["linha"][0] == [-48.0, -15.85]


def test_waze_rota_exige_url_e_login(monkeypatch):
    waze.limpar_cache()
    monkeypatch.delenv("WAZE_FEED_URL", raising=False)
    c = cliente()
    assert c.get("/api/waze").status_code == 401
    entrar(c)
    assert c.get("/api/config").json()["waze"] is False
    assert c.get("/api/waze").status_code == 404
    monkeypatch.setenv("WAZE_FEED_URL", "https://www.waze.com/row-partnerhub-api/partners/1/waze-feeds/abc?format=1")
    monkeypatch.setattr(waze, "_baixar", lambda: FEED)
    r = c.get("/api/waze")
    assert r.status_code == 200 and len(r.json()["alertas"]) == 5
    waze.limpar_cache()


def test_waze_falha_devolve_ultima(monkeypatch):
    waze.limpar_cache()
    monkeypatch.setenv("WAZE_FEED_URL", "https://x")
    waze.dados(lambda: FEED)
    waze._cache["quando"] = 0
    def quebra():
        raise OSError("fora")
    assert waze.dados(quebra)["desatualizado"] is True
    waze.limpar_cache()
