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


def test_cabecalhos_de_seguranca():
    c = cliente()
    r = c.get("/login")
    assert r.headers["x-frame-options"] == "DENY"
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
