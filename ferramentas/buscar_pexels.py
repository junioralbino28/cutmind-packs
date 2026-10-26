"""Junta clipes grátis do Pexels (API oficial) para os vídeos de exemplo dos modelos de montagem.

A licença do Pexels deixa usar de graça, inclusive comercialmente, sem crédito obrigatório; o que
ela proíbe é revender ou repassar o clipe sem alteração, e o exemplo é uma obra editada. Mesmo assim
`fontes.json` guarda o autor e a página de cada clipe, para dar o crédito onde der.

Busca só vídeo em pé (`orientation=portrait`) e baixa o arquivo de 1080×1920 (ou o mais perto
acima disso): nada de corte. Precisa de `PEXELS_API_KEY` no ambiente (chave grátis em
https://www.pexels.com/api/). A chave nunca é impressa.

uso: python -X utf8 ferramentas/buscar_pexels.py <saída> --tema "surf,skate" --quantos 8 [--fotos]
     [--inicio N] [--sem <pasta>] [--evitar palavras]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from buscar_mixkit import em_pe, sonda  # o mesmo tratamento de imagem dos clipes do Mixkit

BUSCA = "https://api.pexels.com/videos/search"
UA = "Mozilla/5.0 (CutMind; exemplos de modelos)"


def _api(params: dict, chave: str) -> dict:
    url = BUSCA + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": chave, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        resto = r.headers.get("X-Ratelimit-Remaining")
        if resto is not None and int(resto) < 20:
            raise SystemExit(f"a cota do Pexels está no fim ({resto} pedidos): parando antes de gastar o resto")
        return json.loads(r.read(5_000_000))


def arquivo_em_pe(video: dict) -> dict | None:
    """O mp4 em pé com pelo menos 1080 de largura, o menor deles (o 4K pesa à toa num exemplo)."""
    bons = [f for f in video.get("video_files", [])
            if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")
            and f["height"] > f["width"] and f["width"] >= 1080]
    return min(bons, key=lambda f: f["width"] * f["height"]) if bons else None


def baixar(url: str, destino: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        destino.write_bytes(r.read(300_000_000))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--tema", required=True, help="termos de busca, separados por vírgula, na ordem em que entram")
    ap.add_argument("--quantos", type=int, required=True)
    ap.add_argument("--fotos", action="store_true", help="um quadro de cada clipe, em JPG")
    ap.add_argument("--evitar", default="", help="palavras do endereço do vídeo que o tiram (ex.: woman,man)")
    ap.add_argument("--inicio", type=int, default=1, help="o número do primeiro arquivo (para juntar duas levas na ordem)")
    ap.add_argument("--sem", type=Path, action="append", default=[],
                    help="pasta de outro exemplo: os clipes dela não entram neste (pode repetir)")
    a = ap.parse_args()
    chave = os.environ.get("PEXELS_API_KEY", "").strip()
    if not chave:
        raise SystemExit("falta PEXELS_API_KEY no ambiente (chave grátis em https://www.pexels.com/api/)")
    a.saida.mkdir(parents=True, exist_ok=True)
    evitar = [x.strip() for x in a.evitar.split(",") if x.strip()]
    termos = [t.strip() for t in a.tema.split(",") if t.strip()]
    arq = a.saida / "fontes.json"
    antes = json.loads(arq.read_text(encoding="utf-8")) if a.inicio > 1 and arq.is_file() else []
    usados = {str(f["id"]) for f in antes}
    for outra in a.sem:
        if (outra / "fontes.json").is_file():
            usados |= {str(f["id"]) for f in json.loads((outra / "fontes.json").read_text(encoding="utf-8"))}
    filas = {}
    for t in termos:
        dados = _api({"query": t, "orientation": "portrait", "size": "medium", "per_page": 40}, chave)
        filas[t] = list(dados.get("videos", []))
        time.sleep(0.5)
    fontes = []
    with tempfile.TemporaryDirectory() as tmp:
        while len(fontes) < a.quantos and any(filas.values()):
            for termo in termos:  # um de cada tema por vez: o exemplo varia
                if len(fontes) >= a.quantos:
                    break
                while filas[termo]:
                    v = filas[termo].pop(0)
                    vid = str(v["id"])
                    pagina = v.get("url", "")
                    slug = pagina.rstrip("/").rsplit("/", 1)[-1] if pagina else vid
                    if vid in usados or any(w in slug.split("-") for w in evitar):
                        continue
                    usados.add(vid)
                    f = arquivo_em_pe(v)
                    if not f or (v.get("duration") or 0) < 4:
                        continue
                    try:
                        bruto = Path(tmp) / f"{vid}.mp4"
                        baixar(f["link"], bruto)
                        w, h, _ = sonda(bruto)
                        nome = slug.removesuffix(f"-{vid}")[:40] or vid
                        k = len(fontes) + a.inicio
                        destino = a.saida / f"{k:02d}-{nome}.{'jpg' if a.fotos else 'mp4'}"
                        em_pe(bruto, destino, a.fotos)
                    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                        print(f"  pulado {slug}: {e.__class__.__name__}")
                        continue
                    fontes.append({"arquivo": destino.name, "id": vid, "termo": termo, "original": f"{w}x{h}",
                                   "pagina": pagina, "autor": (v.get("user") or {}).get("name", ""),
                                   "autor_pagina": (v.get("user") or {}).get("url", ""),
                                   "licenca": "https://www.pexels.com/license/"})
                    print(f"  {destino.name} ({termo}, {w}x{h})", flush=True)
                    break
    arq.write_bytes((json.dumps(antes + fontes, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{len(fontes)} de {a.quantos} em {a.saida}")
    return 0 if len(fontes) >= a.quantos else 1


if __name__ == "__main__":
    sys.exit(main())
