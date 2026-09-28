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
