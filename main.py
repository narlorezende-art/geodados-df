"""GeoDados DF — servidor em Python (FastAPI).

Tudo (mapa, dados e biblioteca 3D) só é entregue a quem fez login.
Variáveis de ambiente:
  USERS            usuários e senhas com hash (gere com scripts/criar_usuario.py)
  SESSION_SECRET   texto aleatório longo que assina as sessões
  GOOGLE_MAPS_KEY  (opcional) prédios 3D fotorrealistas do Google
  CESIUM_ION_TOKEN (opcional) relevo e prédios do Cesium ion
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import clima
import dados
import seguranca

# Todos os arquivos ficam na mesma pasta (sem subpastas), exceto a biblioteca
# 3D em cesium/, que é baixada automaticamente no build.
BASE = Path(__file__).resolve().parent
PAGINA_LOGIN = BASE / "login.html"
PAINEL = {  # únicos arquivos da pasta que o navegador pode receber
    "index.html": "text/html",
    "app.js": "text/javascript",
    "app.css": "text/css",
}

COOKIE = "gd_session"
SESSAO_HORAS = 12
TENTATIVAS_MAX = 8          # erros de senha por IP…
JANELA_TENTATIVAS = 15 * 60  # …a cada 15 minutos
ROTAS_LIVRES = {"/login", "/logout", "/favicon.svg", "/robots.txt", "/saude"}

EM_PRODUCAO = bool(os.environ.get("RENDER")) or os.environ.get("HTTPS_ONLY") == "1"

CABECALHOS_SEGURANCA = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Robots-Tag": "noindex, nofollow",
}
if EM_PRODUCAO:
    CABECALHOS_SEGURANCA["Strict-Transport-Security"] = "max-age=31536000"

app = FastAPI(title="GeoDados DF", docs_url=None, redoc_url=None, openapi_url=None)
_falhas: dict[str, deque] = defaultdict(deque)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def _serializador() -> URLSafeTimedSerializer:
    segredo = os.environ.get("SESSION_SECRET", "")
    return URLSafeTimedSerializer(segredo, salt="geodados-sessao")


def usuario_da_sessao(request: Request) -> str | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        dados_sessao = _serializador().loads(token, max_age=SESSAO_HORAS * 3600)
    except (BadSignature, SignatureExpired):
        return None
    usuario = dados_sessao.get("u")
    # quem saiu da lista USERS perde o acesso na hora
    return usuario if usuario in seguranca.carregar_usuarios() else None


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _bloqueado(ip: str) -> bool:
    fila, agora = _falhas[ip], time.monotonic()
    while fila and agora - fila[0] > JANELA_TENTATIVAS:
        fila.popleft()
    return len(fila) >= TENTATIVAS_MAX


def _proximo_seguro(destino: str) -> str:
    if not destino.startswith("/") or destino.startswith(("//", "/\\", "/login")):
        return "/"
    return destino


@app.middleware("http")
async def exigir_login(request: Request, call_next):
    if request.url.path == "/saude":
        return await call_next(request)
    if not os.environ.get("SESSION_SECRET") or not os.environ.get("USERS"):
        return PlainTextResponse(
            "Configuração incompleta: defina USERS e SESSION_SECRET (veja o README).", status_code=500
        )
    caminho = request.url.path
    if caminho not in ROTAS_LIVRES:
        usuario = usuario_da_sessao(request)
        if not usuario:
            quer_pagina = request.method == "GET" and "text/html" in request.headers.get("accept", "")
            if quer_pagina:
                prox = "" if caminho == "/" else "?next=" + quote(caminho + (f"?{request.url.query}" if request.url.query else ""))
                resposta = RedirectResponse(f"/login{prox}", status_code=302)
            else:
                resposta = PlainTextResponse("Sessão expirada. Entre novamente.", status_code=401)
            return _com_cabecalhos(resposta)
        request.state.usuario = usuario
    resposta = await call_next(request)
    if caminho.startswith(("/cesium/", "/app.", "/favicon")):
        resposta.headers.setdefault("Cache-Control", "private, max-age=3600")
    else:
        resposta.headers["Cache-Control"] = "private, no-store"
    return _com_cabecalhos(resposta)


def _com_cabecalhos(resposta: Response) -> Response:
    for k, v in CABECALHOS_SEGURANCA.items():
        resposta.headers[k] = v
    return resposta


# ---------------- rotas livres ----------------

@app.get("/login")
def pagina_login(request: Request):
    if usuario_da_sessao(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(PAGINA_LOGIN, media_type="text/html")


@app.post("/login")
def entrar(request: Request, usuario: str = Form(""), senha: str = Form(""), next: str = Form("/")):
    ip, prox = _ip(request), _proximo_seguro(next)
    sufixo = "" if prox == "/" else "&next=" + quote(prox)
    if _bloqueado(ip):
        return RedirectResponse(f"/login?erro=limite{sufixo}", status_code=302)

    usuario = usuario.strip().lower()
    guardado = seguranca.carregar_usuarios().get(usuario)
    if guardado and seguranca.conferir_senha(senha, guardado):
        _falhas.pop(ip, None)
        resposta = RedirectResponse(prox, status_code=302)
        resposta.set_cookie(
            COOKIE, _serializador().dumps({"u": usuario}), max_age=SESSAO_HORAS * 3600,
            httponly=True, secure=EM_PRODUCAO, samesite="lax", path="/",
        )
        return resposta

    if not guardado:
        seguranca.gastar_tempo(senha)
    _falhas[ip].append(time.monotonic())
    return RedirectResponse(f"/login?erro=1{sufixo}", status_code=302)


@app.get("/logout")
def sair():
    resposta = RedirectResponse("/login", status_code=302)
    resposta.delete_cookie(COOKIE, path="/")
    return resposta


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"


@app.get("/saude", response_class=PlainTextResponse)
def saude():
    return "ok"


@app.get("/favicon.svg")
def favicon():
    return FileResponse(BASE / "favicon.svg", media_type="image/svg+xml")


# ---------------- rotas protegidas ----------------

@app.get("/api/me")
def quem_sou(request: Request):
    return {"user": request.state.usuario}


@app.get("/api/config")
def configuracao():
    return {
        "googleMapsKey": os.environ.get("GOOGLE_MAPS_KEY", ""),
        "cesiumIonToken": os.environ.get("CESIUM_ION_TOKEN", ""),
    }


@app.get("/data/equipamentos.json")
def lista_equipamentos():
    return JSONResponse(dados.equipamentos())


@app.get("/api/clima")
def previsao_do_tempo():
    try:
        return clima.previsao()
    except RuntimeError as erro:
        return JSONResponse({"erro": str(erro)}, status_code=503)


@app.get("/")
def painel():
    return FileResponse(BASE / "index.html", media_type="text/html")


@app.get("/{arquivo}")
def arquivo_do_painel(arquivo: str):
    # só a lista PAINEL é servida: .py, .csv e demais arquivos nunca saem do servidor
    if arquivo not in PAINEL:
        return PlainTextResponse("Não encontrado.", status_code=404)
    return FileResponse(BASE / arquivo, media_type=PAINEL[arquivo])


# motor 3D (baixado no build por baixar_cesium.py)
app.mount("/cesium", StaticFiles(directory=BASE / "cesium", check_dir=False), name="cesium")
