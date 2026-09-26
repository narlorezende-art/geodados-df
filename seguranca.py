"""Senhas (PBKDF2-SHA256) e lista de usuários vinda da variável de ambiente USERS."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

ALGORITMO = "pbkdf2_sha256"
ITERACOES = 600_000  # recomendação OWASP para PBKDF2-SHA256


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def gerar_hash(senha: str, iteracoes: int = ITERACOES) -> str:
    """Retorna 'pbkdf2_sha256$<iteracoes>$<sal>$<hash>'."""
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, iteracoes)
    return f"{ALGORITMO}${iteracoes}${_b64(sal)}${_b64(dk)}"


def conferir_senha(senha: str, guardado: str) -> bool:
    """Compara em tempo constante. Aceita hash PBKDF2 ou (não recomendado) senha em texto."""
    if guardado.startswith(ALGORITMO + "$"):
        try:
            _, it, sal, esperado = guardado.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), _unb64(sal), int(it))
            return hmac.compare_digest(dk, _unb64(esperado))
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(senha.encode(), guardado.encode())


_HASH_FALSO = gerar_hash("x", 1000)


def gastar_tempo(senha: str) -> None:
    """Mesmo custo de uma conferência real, para não revelar se o usuário existe."""
    hashlib.pbkdf2_hmac("sha256", senha.encode(), b"0" * 16, ITERACOES)


def carregar_usuarios(bruto: str | None = None) -> dict[str, str]:
    """USERS = 'narlo:pbkdf2_sha256$...;maria:pbkdf2_sha256$...' (separe por ; ou quebra de linha)."""
    bruto = os.environ.get("USERS", "") if bruto is None else bruto
    usuarios: dict[str, str] = {}
    for parte in bruto.replace("\n", ";").split(";"):
        nome, sep, valor = parte.strip().partition(":")
        if sep and nome.strip() and valor.strip():
            usuarios[nome.strip().lower()] = valor.strip()
    return usuarios
