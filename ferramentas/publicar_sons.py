"""Publica os efeitos sonoros virais na biblioteca: acerta cada som, sobe e grava a lista do kit.

São os sons de meme, marca e série que circulam em todo Reels (Taco Bell, Discord, Dexter, cha-ching…).
O áudio NÃO vai para o Git: só para a Release `--release` deste repositório, de onde o kit baixa o som
na primeira vez que alguém ouve ou usa. A lista (`sons.json`) vai junto com o kit em
`assets/sfx/virais.json` e não entra no `catalogo.json` da biblioteca: um tipo novo ali faria os kits
antigos recusarem o catálogo inteiro.

A lista de entrada (`sons/lista.json`) diz id, arquivo, nome, nome em inglês e uso. Cada som sai:
- sem o silêncio do começo (o que fica abaixo de -40 dB do pico, menos 5 ms de folga) e da cauda
  (abaixo de -60 dB, com 10 ms de saída suave);
- com o pico em -3 dBFS, 44,1 kHz, nos canais que o arquivo tem, MP3 128k sem metadado (bit a bit
  igual a cada vez);
- com o `golpe` (quando o som chega a 25% do pico, medido no MP3 já pronto: quem posiciona desconta)
  e o `volume` sugerido. Com `volume_ref` na lista (o volume que o arquivo ORIGINAL teve numa mixagem
  aprovada no ouvido), o volume é esse, convertido para o arquivo acertado: soa igual. Sem ele, a
  conta do `efeitos_sonoros.volume_sugerido` do kit, que exagera em som muito curto (um clique).

`--local <pasta>` não sobe nada: grava a mesma árvore da Release e a lista numa pasta, para testar.

uso: uv run --project <kit> python -X utf8 ferramentas/publicar_sons.py <pasta dos áudios>
     --release sons-1 [--lista sons/lista.json] [--kit <raiz do kit>] [--local <pasta>]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from publicar_trilhas import BASE, REPO, sha256, subir

RAIZ = Path(__file__).resolve().parent.parent
SR = 44100
PICO = 10 ** (-3 / 20)
SILENCIO_DB = -40.0
CAUDA_DB = -60.0
ALVO_RMS = -26.0  # o mesmo alvo do kit: ~12 dB abaixo da voz normalizada
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")


def canais(p: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                          "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def ler(p: Path) -> np.ndarray:
    """(amostras, canais) em float, nos canais que o arquivo tem (nada de -ac: muda o nível)."""
    n = canais(p)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(p), "-f", "f32le", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, n).astype(np.float64)


def acertar(y: np.ndarray) -> tuple[np.ndarray, float]:
    """O som acertado e o pico do original (o ganho aplicado é PICO / pico)."""
    env = np.abs(y).max(axis=1)
    pico = float(env.max())
    acima = np.flatnonzero(env > pico * 10 ** (SILENCIO_DB / 20))
    ini = max(0, int(acima[0]) - int(0.005 * SR))
    fim = min(len(env), int(np.flatnonzero(env > pico * 10 ** (CAUDA_DB / 20))[-1]) + int(0.010 * SR))
    y = y[ini:fim] / pico * PICO
    n_in, n_out = int(0.002 * SR), int(0.010 * SR)
    y[:n_in] *= np.linspace(0, 1, n_in)[:, None]
    y[-n_out:] *= np.linspace(1, 0, n_out)[:, None]
    return y, pico


def gravar_mp3(y: np.ndarray, destino: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "som.wav"
        with wave.open(str(wav), "w") as w:
            w.setnchannels(y.shape[1])
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(wav), "-map_metadata", "-1",
                        "-fflags", "+bitexact", "-flags:a", "+bitexact", "-c:a", "libmp3lame", "-b:a", "128k",
                        str(destino)], check=True)


def medir(mp3: Path) -> dict:
    y = ler(mp3)
    env = np.abs(y).max(axis=1)
    pico = env.max()
    assert pico <= 10 ** (-1 / 20), f"{mp3.name}: pico {20 * np.log10(pico):.1f} dBFS depois do MP3"
    golpe = int(np.argmax(env > 0.25 * pico)) / SR
    mono = y.mean(axis=1)
    i = int(golpe * SR)
    rms = 20 * np.log10(np.sqrt(np.mean(mono[i:i + int(0.3 * SR)] ** 2)) + 1e-12)
    volume = round(float(np.clip(10 ** ((ALVO_RMS - rms) / 20), 0.1, 1.0)), 2)
    return {"duracao": round(len(y) / SR, 3), "golpe": round(golpe, 3), "volume": volume}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audios", type=Path)
    ap.add_argument("--release", required=True)
    ap.add_argument("--lista", type=Path, default=RAIZ / "sons" / "lista.json")
    ap.add_argument("--kit", type=Path)
    ap.add_argument("--local", type=Path)
    a = ap.parse_args()
    lista = json.loads(a.lista.read_text(encoding="utf-8"))
    itens, arquivos = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for s in lista:
            sid = s["id"]
            assert _ID.fullmatch(sid), f"id inválido: {sid}"
            mp3 = Path(tmp) / f"{sid}.mp3"
            y, pico = acertar(ler(a.audios / s["arquivo"]))
            gravar_mp3(y, mp3)
            m = medir(mp3)
            if s.get("volume_ref") is not None:
                m["volume"] = round(float(np.clip(s["volume_ref"] * pico / PICO, 0.05, 1.0)), 2)
            itens.append({"id": sid, "tipo": "som", "nome": s["nome"], "nome_en": s["nome_en"], "uso": s["uso"],
                          "viral": True, **m, "release": a.release, "arquivo": mp3.name,
                          "tamanho": mp3.stat().st_size, "sha256": sha256(mp3)})
            arquivos.append(mp3)
            print(f"{sid:<16} {m['duracao']:6.3f} s  golpe {m['golpe']:.3f}  volume {m['volume']:.2f}", flush=True)
        if a.local:
            destino = a.local / a.release
            destino.mkdir(parents=True, exist_ok=True)
            for f in arquivos:
                shutil.copy2(f, destino / f.name)
        else:
            subir(a.release, arquivos, f"Efeitos sonoros ({a.release})")
    cat = {"versao": 1, "repo": REPO, "base": BASE, "gerado": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "pacotes": itens}
    cat_p = (a.local / "sons.json") if a.local else RAIZ / "sons.json"
    cat_p.parent.mkdir(parents=True, exist_ok=True)
    cat_p.write_bytes((json.dumps(cat, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if a.kit:
        shutil.copy2(cat_p, a.kit / "assets" / "sfx" / "virais.json")
    print(f"{len(itens)} som(ns) → {cat_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
