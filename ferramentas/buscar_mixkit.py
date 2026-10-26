"""Junta clipes grátis do Mixkit para os vídeos de exemplo dos modelos de montagem.

Só entra vídeo da licença gratuita do Mixkit ("Mixkit Stock Video Free License": uso comercial, sem
crédito; o que ela proíbe é repassar o clipe cru como banco de imagens, e o exemplo é uma obra
editada). Os de licença "Restricted" (só uso não comercial) ficam de fora: a licença vem da própria
página de cada vídeo. O clipe em pé entra como está; o deitado é cortado no centro para 9:16, a
partir da versão 1080 (o corte de um 720 fica mole). `fontes.json` guarda de onde veio cada um.

O arquivo vem do endereço antigo (`/videos/<id>/<id>-1080.mp4`) quando ele existe; os vídeos mais
novos só têm o `contentUrl` da página, em 720p (o botão de download em 1080 passa por um desafio
anti-robô). Deitado abaixo de 1080 de altura fica de fora: o corte 9:16 sairia mole. No primeiro 429
o script para e guarda o que já juntou.

Para "Fotos com zoom" (`--fotos`), sai um quadro nítido do meio de cada clipe, em JPG.

uso: python -X utf8 ferramentas/buscar_mixkit.py <saída> --tema "surf,skateboard,snowboard" --quantos 16 [--fotos]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (CutMind; exemplos de modelos)"}
ITEM = re.compile(r'href="/free-stock-video/([a-z0-9-]+)-(\d+)/"')
# a licença do vídeo é o `data-license` da página dele. O campo "license" dos dados estruturados
# diz "#videoFree" até em vídeo Restricted (é fixo no modelo da página): não serve para decidir
LICENCA = re.compile(r'data-license="(video\w+)"')
AVISO = re.compile(r'"copyrightNotice":"([^"]*)"')
CONTEUDO = re.compile(r'"contentUrl":"(https://assets\.mixkit\.co/[A-Za-z0-9/._-]+)"')
PAUSA = 2.0  # entre um pedido e outro: com 0,4 s o site passou a barrar este cliente por horas


class Freado(Exception):
    """O site pediu para esperar (429): parar, não insistir."""


class Desafio(Exception):
    """Página atrás do desafio anti-robô (a busca, para termo que não é categoria): pular, não parar."""


def _get(url: str, limite: int = 2_000_000) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read(limite)
    except urllib.error.HTTPError as e:
        if e.code == 429 and (e.headers.get("Cf-Mitigated") or "").lower() == "challenge":
            raise Desafio(url) from e
        if e.code == 429:
            raise Freado(f"429 em {url} (Retry-After: {e.headers.get('Retry-After') or 'não informado'})") from e
        raise


def candidatos(termo: str, paginas: int = 2) -> list[tuple[str, str]]:
    vistos, out = set(), []
    slug = re.sub(r"[^a-z0-9]+", "-", termo.lower()).strip("-")
    for p in range(1, paginas + 1):
        try:
            html = _get(f"https://mixkit.co/free-stock-video/{slug}/" + (f"?page={p}" if p > 1 else "")).decode("utf-8", "replace")
        except urllib.error.HTTPError:
            break
        except Desafio:
            print(f"  tema sem página própria no Mixkit (cai na busca, que tem desafio anti-robô): {termo}")
            break
        for nome, vid in ITEM.findall(html):
            if vid not in vistos:
                vistos.add(vid)
                out.append((nome, vid))
        time.sleep(PAUSA)
    return out


def pagina(nome: str, vid: str) -> str:
    return _get(f"https://mixkit.co/free-stock-video/{nome}-{vid}/").decode("utf-8", "replace")


def licenca_gratis(html: str) -> bool:
    tipos = set(LICENCA.findall(html))
    aviso = AVISO.search(html)
    return tipos == {"videoFree"} and not (aviso and "Restricted" in aviso.group(1))


def baixar(vid: str, html: str, destino: Path) -> None:
    """O 1080 do endereço antigo; sem ele, o `contentUrl` da página (720p)."""
    try:
        destino.write_bytes(_get(f"https://assets.mixkit.co/videos/{vid}/{vid}-1080.mp4", 200_000_000))
        return
    except urllib.error.HTTPError:
        pass
    m = CONTEUDO.search(html)
    if not m:
        raise ValueError("a página não traz o endereço do vídeo")
    destino.write_bytes(_get(m.group(1), 200_000_000))


def sonda(p: Path) -> tuple[int, int, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float(d["format"]["duration"])


def em_pe(origem: Path, destino: Path, foto: bool) -> None:
    """9:16 a 1080×1920: o em pé como está, o deitado cortado no centro. `foto`: um quadro do meio."""
    w, h, dur = sonda(origem)
    corte = "" if h >= w else "crop=ih*9/16:ih,"
    filtro = f"{corte}scale=1080:1920:flags=lanczos,setsar=1"
    if foto:
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(origem), "-frames:v", "1",
                        "-vf", filtro, "-q:v", "2", str(destino)], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(origem), "-t", "12", "-an", "-vf", filtro,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(destino)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--tema", required=True, help="termos de busca, separados por vírgula, na ordem em que entram")
    ap.add_argument("--quantos", type=int, required=True)
    ap.add_argument("--fotos", action="store_true", help="um quadro de cada clipe, em JPG")
    ap.add_argument("--evitar", default="", help="palavras do nome do vídeo que o tiram (ex.: woman,man,girl)")
    ap.add_argument("--inicio", type=int, default=1, help="o número do primeiro arquivo (para juntar duas levas na ordem)")
    ap.add_argument("--sem", type=Path, action="append", default=[],
                    help="pasta de outro exemplo: os clipes dela não entram neste (pode repetir)")
    a = ap.parse_args()
    a.saida.mkdir(parents=True, exist_ok=True)
    evitar = [x.strip() for x in a.evitar.split(",") if x.strip()]
    termos = [t.strip() for t in a.tema.split(",") if t.strip()]
    arq = a.saida / "fontes.json"
    antes = json.loads(arq.read_text(encoding="utf-8")) if a.inicio > 1 and arq.is_file() else []
    # numa segunda leva, o que já está na pasta não volta
    fontes, usados = [], {f["id"] for f in antes}
    for outra in a.sem:
        if (outra / "fontes.json").is_file():
            usados |= {f["id"] for f in json.loads((outra / "fontes.json").read_text(encoding="utf-8"))}
    freio = None
    try:
        filas = {t: candidatos(t) for t in termos}
    except Freado as e:
        filas, freio = {}, e
    with tempfile.TemporaryDirectory() as tmp:
        while not freio and len(fontes) < a.quantos and any(filas.values()):
            for termo in termos:  # um de cada tema por vez: o exemplo varia
                if freio or len(fontes) >= a.quantos:
                    break
                while filas[termo]:
                    nome, vid = filas[termo].pop(0)
                    if vid in usados or any(w in nome.split("-") for w in evitar):
                        continue
                    usados.add(vid)
                    try:
                        html = pagina(nome, vid)
                        time.sleep(PAUSA)
                        if not licenca_gratis(html):
                            print(f"  fora (licença Restricted): {nome}-{vid}")
                            continue
                        bruto = Path(tmp) / f"{vid}.mp4"
                        baixar(vid, html, bruto)
                        w, h, dur = sonda(bruto)
                        if dur < 3:
                            continue
                        if w > h and h < 1080:
                            print(f"  fora (deitado em {w}x{h}, o corte 9:16 fica mole): {nome}-{vid}")
                            continue
                        k = len(fontes) + a.inicio
                        destino = a.saida / f"{k:02d}-{nome[:40]}.{'jpg' if a.fotos else 'mp4'}"
                        em_pe(bruto, destino, a.fotos)
                    except Freado as e:
                        freio = e
                        break
                    except Desafio:
                        print(f"  pulado {nome}-{vid}: desafio anti-robô")
                        continue
                    except (urllib.error.URLError, subprocess.CalledProcessError, OSError, KeyError, ValueError) as e:
                        print(f"  pulado {nome}-{vid}: {e.__class__.__name__} {getattr(e, 'code', '')}".rstrip())
                        continue
                    fontes.append({"arquivo": destino.name, "id": vid, "termo": termo, "original": f"{w}x{h}",
                                   "pagina": f"https://mixkit.co/free-stock-video/{nome}-{vid}/",
                                   "licenca": "https://mixkit.co/license/#videoFree"})
                    print(f"  {destino.name} ({termo}, {w}x{h})", flush=True)
                    time.sleep(PAUSA)
                    break
    arq.write_bytes((json.dumps(antes + fontes, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if freio:
        print(f"parado: {freio}. O que já veio ficou salvo; rode de novo mais tarde com --inicio {len(antes) + len(fontes) + 1}")
    print(f"{len(fontes)} de {a.quantos} em {a.saida}")
    return 0 if len(fontes) >= a.quantos else 1


if __name__ == "__main__":
    sys.exit(main())
