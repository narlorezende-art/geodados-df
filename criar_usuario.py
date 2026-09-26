"""Gera a linha de um usuário para a variável USERS, com a senha protegida (PBKDF2).

Uso:
    python criar_usuario.py narlo            (a senha é pedida sem aparecer na tela)
    python criar_usuario.py narlo MinhaSenha

Junte as linhas de várias pessoas com ponto e vírgula:  narlo:pbkdf2_sha256$...;maria:pbkdf2_sha256$...
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seguranca import gerar_hash  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
usuario = sys.argv[1].strip().lower()
senha = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass(f"Senha para {usuario}: ")
if len(senha) < 10:
    sys.exit("Use uma senha com pelo menos 10 caracteres.")
if ":" in usuario or ";" in usuario:
    sys.exit("O nome de usuário não pode ter ':' nem ';'.")
print(f"{usuario}:{gerar_hash(senha)}")
