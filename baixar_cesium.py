"""Baixa a biblioteca CesiumJS (motor do globo 3D) para a pasta cesium/.
Roda automaticamente no build do Render; localmente, rode uma vez antes de iniciar.
"""
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSAO = "1.145.0"
URL = f"https://registry.npmjs.org/cesium/-/cesium-{VERSAO}.tgz"
DESTINO = Path(__file__).resolve().parent / "cesium"
PREFIXO = "package/Build/Cesium/"

marcador = DESTINO / ".versao"
if (DESTINO / "Cesium.js").exists() and marcador.exists() and marcador.read_text().strip() == VERSAO:
    print(f"CesiumJS {VERSAO} já está em {DESTINO}")
    sys.exit(0)

print(f"Baixando CesiumJS {VERSAO}…")
with urllib.request.urlopen(URL, timeout=120) as r:
    pacote = io.BytesIO(r.read())

shutil.rmtree(DESTINO, ignore_errors=True)
with tarfile.open(fileobj=pacote, mode="r:gz") as tar:
    for m in tar.getmembers():
        if not m.isfile() or not m.name.startswith(PREFIXO):
            continue
        rel = m.name[len(PREFIXO):]
        if rel in ("index.js", "index.cjs") or ".." in rel:
            continue
        alvo = DESTINO / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(tar.extractfile(m).read())
(DESTINO / ".versao").write_text(VERSAO)
print(f"CesiumJS {VERSAO} instalado em {DESTINO}")
