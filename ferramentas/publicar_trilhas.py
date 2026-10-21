"""Publica trilhas na biblioteca do kit: normaliza, faz a prévia, sobe e atualiza o catálogo.

A pasta de entrada tem os áudios e um `trilhas.json`:

    [{"arquivo": "manha.mp3", "id": "calma-01", "nome": "Manhã leve", "clima": "calma",
      "tags": ["violão", "acústica"]}]

Para cada trilha:
- normaliza em -14 LUFS (duas passadas do loudnorm, pico -1 dB), 48 kHz, AAC 160k:
  `<id>.m4a`. O volume de fundo do kit (15%) parte daqui;
- faz a prévia: os primeiros 20 s, saindo devagar, AAC 96k: `<id>.previa.m4a`;
- mede duração, tamanho e sha256.

Depois:
- sobe para a Release `--release` deste repositório e confere tamanho e sha256 no GitHub;
- regrava o `catalogo.json` da raiz (o mesmo id é trocado, o resto fica);
- sobe o catálogo para a Release `catalogo`: o kit pega com `pacotes.py atualizar`, sem
  precisar de versão nova;
- com `--kit`, copia o catálogo também para `<kit>/assets/pacotes/catalogo.json`.

`--local <pasta>` não sobe nada: monta a mesma árvore da Release numa pasta, para testar
(servir a pasta por HTTP e apontar CENNO_PACOTES_BASE para ela).

uso: python -X utf8 ferramentas/publicar_trilhas.py <pasta> --release trilhas-1 [--kit <raiz do kit>] [--local <pasta>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = "junioralbino28/cenno-edit-packs"
BASE = f"https://github.com/{REPO}/releases/download"
RAIZ = Path(__file__).resolve().parent.parent
PREVIA_S = 20
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")


def ff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True)


def duracao(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                          str(p)], capture_output=True, text=True, check=True).stdout
    return round(float(out.strip()), 3)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def normalizar(src: Path, dst: Path) -> None:
    """Duas passadas: a primeira mede, a segunda aplica com ganho linear (não mexe na dinâmica)."""
    alvo = "I=-14:TP=-1:LRA=11"
    r = ff("-i", str(src), "-af", f"loudnorm={alvo}:print_format=json", "-f", "null", "-")
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    filtro = (f"loudnorm={alvo}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true")
    ff("-i", str(src), "-vn", "-af", filtro, "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "160k",
       "-movflags", "+faststart", str(dst))


def previa(src: Path, dst: Path, dur: float) -> None:
    d = min(PREVIA_S, dur)
    ff("-i", str(src), "-t", f"{d:.3f}", "-af", f"afade=t=out:st={max(0.0, d - 1.5):.3f}:d=1.5",
       "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst))


def gh(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r


def subir(release: str, arquivos: list[Path], titulo: str) -> None:
    if subprocess.run(["gh", "release", "view", release, "-R", REPO], capture_output=True).returncode != 0:
        gh("release", "create", release, "-R", REPO, "--title", titulo, "--notes", "Pacotes do kit. Ver o catalogo.json.")
    gh("release", "upload", release, *map(str, arquivos), "-R", REPO, "--clobber")
    no_github = {a["name"]: a for a in json.loads(gh("api", f"repos/{REPO}/releases/tags/{release}").stdout)["assets"]}
    for f in arquivos:
        a = no_github.get(f.name)
        assert a and a["size"] == f.stat().st_size, f"{f.name}: tamanho no GitHub não confere"
        dig = (a.get("digest") or "").removeprefix("sha256:")
        assert not dig or dig == sha256(f), f"{f.name}: sha256 no GitHub não confere"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta", type=Path)
    ap.add_argument("--release", required=True)
    ap.add_argument("--kit", type=Path)
    ap.add_argument("--local", type=Path)
    a = ap.parse_args()
    lista = json.loads((a.pasta / "trilhas.json").read_text(encoding="utf-8"))
    cat_p = (a.local / "catalogo" / "catalogo.json") if a.local else RAIZ / "catalogo.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8")) if cat_p.is_file() else {
        "versao": 1, "repo": REPO, "base": BASE, "pacotes": []}
    novos, arquivos = [], []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for t in lista:
            pid = t["id"]
            assert _ID.fullmatch(pid), f"id inválido: {pid}"
            musica, pv = out / f"{pid}.m4a", out / f"{pid}.previa.m4a"
            normalizar(a.pasta / t["arquivo"], musica)
            dur = duracao(musica)
            previa(musica, pv, dur)
            novos.append({"id": pid, "tipo": "trilha", "nome": t["nome"], "clima": t.get("clima", ""),
                          "tags": t.get("tags", []), "duracao": dur, "release": a.release,
                          "arquivo": musica.name, "tamanho": musica.stat().st_size, "sha256": sha256(musica),
                          "previa": {"arquivo": pv.name, "tamanho": pv.stat().st_size, "sha256": sha256(pv)}})
            arquivos += [musica, pv]
            print(f"{pid}: {dur:.1f} s, {musica.stat().st_size / 1e6:.1f} MB + prévia "
                  f"{pv.stat().st_size / 1e3:.0f} KB", flush=True)
        if a.local:
            destino = a.local / a.release
            destino.mkdir(parents=True, exist_ok=True)
            for f in arquivos:
                shutil.copy2(f, destino / f.name)
        else:
            subir(a.release, arquivos, f"Trilhas ({a.release})")
    ids = {n["id"] for n in novos}
    cat["pacotes"] = [p for p in cat["pacotes"] if p["id"] not in ids] + novos
    cat["gerado"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cat_p.parent.mkdir(parents=True, exist_ok=True)
    cat_p.write_bytes((json.dumps(cat, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if not a.local:
        subir("catalogo", [cat_p], "Catálogo")
    if a.kit:
        shutil.copy2(cat_p, a.kit / "assets" / "pacotes" / "catalogo.json")
    print(f"catálogo: {len(cat['pacotes'])} pacote(s), {len(novos)} desta vez → {cat_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
