"""Faz o vídeo de exemplo de cada modelo de montagem.

As imagens são clipes grátis do Mixkit (`buscar_mixkit.py`, só a licença gratuita), com
`--midias`, na ordem do `ordem.txt` da pasta quando ele existe; sem eles, cartões numerados. A música é uma batida gerada aqui (120 BPM, 4 compassos
calmos, o drop no 5º e 8 compassos cheios): o exemplo não leva música de ninguém.
O vídeo sai do próprio kit (`montagem.py usar`), então mostra exatamente o que o modelo faz: os
cortes na batida, o drop, os textos, o zoom e as transições.

Roda com o ambiente do kit (numpy e Pillow vêm dele):

uso: uv run --project <kit> python -X utf8 ferramentas/previa_montagem.py <pasta dos modelos> <saída> --kit <kit>
     [--midias <pasta com uma subpasta por modelo>] [--so <id>]

Para cada `<pasta dos modelos>/<id>.json` sai `<saída>/<id>.mp4` (720×1280, leve, para baixar no
celular), mais o projeto inteiro em `<saída>/projetos/<id>/` para conferir.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SR = 44100
BPM = 120
CALMOS, CHEIOS = 4, 8  # compassos antes e depois do drop
CORES = ["#F87000", "#1F6FEB", "#008810", "#8E44AD", "#E5484D", "#0F9D9A", "#C77D00", "#3D5AFE"]


# ---- a música ----
def _env(n: int, ataque: float, queda: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(ataque, 1e-4)) * np.exp(-t / queda)


def _bumbo(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    freq = 45 + 75 * np.exp(-t / 0.04)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * _env(n, 0.001, 0.22)


def _ruido(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(-1, 1, n)


def _agudo(x: np.ndarray, a: float = 0.85) -> np.ndarray:
    """Tira o grave do ruído (filtro de um polo): o chiado do chimbal."""
    y = np.empty_like(x)
    ant = 0.0
    for i, v in enumerate(x):
        ant = a * ant + (1 - a) * v
        y[i] = v - ant
    return y


def _grave(x: np.ndarray, a: float) -> np.ndarray:
    y = np.empty_like(x)
    ant = 0.0
    for i, v in enumerate(x):
        ant = a * ant + (1 - a) * v
        y[i] = ant
    return y


def _serra(freq: float, n: int) -> np.ndarray:
    fase = (np.arange(n) * freq / SR) % 1.0
    return 2 * fase - 1


def musica(destino: Path) -> float:
    """A batida do exemplo. Devolve a duração em segundos."""
    rng = np.random.default_rng(7)
    batida = 60 / BPM
    compasso = 4 * batida
    total = CALMOS + CHEIOS + 1  # mais um compasso de fim
    n = int(total * compasso * SR)
    mix = np.zeros(n)
    nb = int(batida * SR)
    bumbo = _bumbo(int(0.35 * SR))
    palma = (_agudo(_ruido(int(0.2 * SR), rng), 0.6) * 0.9 + np.sin(2 * np.pi * 190 * np.arange(int(0.2 * SR)) / SR) * 0.3) \
        * _env(int(0.2 * SR), 0.001, 0.07)
    chimbal = _agudo(_ruido(int(0.06 * SR), rng)) * _env(int(0.06 * SR), 0.0005, 0.015)
    # Lá menor, Fá, Dó, Sol: a fundamental do baixo e as três notas do acorde de cada compasso
    acordes = [(110.0, (220.0, 261.63, 329.63)), (87.31, (174.61, 220.0, 261.63)),
               (130.81, (261.63, 329.63, 392.0)), (98.0, (196.0, 246.94, 293.66))]

    def pos(c: int, b: float) -> int:
        return int((c * compasso + b * batida) * SR)

    def por(som: np.ndarray, i: int, ganho: float) -> None:
        j = min(n, i + len(som))
        if i < n:
            mix[i:j] += ganho * som[: j - i]

    for c in range(total):
        cheio = CALMOS <= c < CALMOS + CHEIOS
        fim = c == total - 1
        raiz, notas = acordes[c % 4]
        # o colchão do acorde (mais baixo na parte calma, sumindo no fim)
        nc = int(compasso * SR)
        colchao = sum(_serra(f, nc) for f in notas) / 3
        colchao = _grave(colchao, 0.93 if cheio else 0.97) * _env(nc, 0.08, 3.0)
        por(colchao, pos(c, 0), 0.18 if cheio else 0.12)
        if fim:
            por(bumbo, pos(c, 0), 1.0)
            continue
        for b in range(4):
            # bumbo em todo tempo também na parte calma (mais baixo): só no tempo 1, o detector
            # achava batida no chimbal do contratempo e a grade da introdução saía torta
            por(bumbo, pos(c, b), 1.0 if cheio else 0.4)
            if cheio and b in (1, 3):
                por(palma, pos(c, b), 0.55)
            por(chimbal, pos(c, b + 0.5), 0.35 if cheio else 0.12)
            if cheio:
                por(chimbal, pos(c, b), 0.15)
                # o baixo nas colcheias, com a fundamental do acorde
                nn = nb // 2
                baixo = (np.sin(2 * np.pi * raiz * np.arange(nn) / SR) + 0.3 * _serra(raiz, nn)) * _env(nn, 0.005, 0.18)
                por(baixo, pos(c, b), 0.45)
                por(baixo, pos(c, b + 0.5), 0.35)
    mix /= np.max(np.abs(mix)) / 0.89
    estereo = np.stack([mix, mix], axis=1)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((estereo * 32767).astype("<i2").tobytes())
    return n / SR


# ---- os cartões ----
def cartoes(pasta: Path, quantos: int, tamanho: tuple[int, int]) -> list[Path]:
    """Um cartão por lugar, com o número dele: é onde entra a foto ou o vídeo de quem usa."""
    pasta.mkdir(parents=True, exist_ok=True)
    w, h = tamanho
    # a fonte embutida do Pillow (escala sem depender das fontes do sistema) não tem acento: o
    # rótulo fica sem ("FOTO OU CLIPE"). O número vai para baixo (80% da altura): os textos dos
    # modelos ocupam de 13% a 69%, e o número no meio ficava embaixo de "SIGA PARA MAIS"
    grande = ImageFont.load_default(size=int(min(w, h) * 0.26))
    pequena = ImageFont.load_default(size=int(min(w, h) * 0.045))
    feitos = []
    for k in range(1, quantos + 1):
        im = Image.new("RGB", (w, h), CORES[(k - 1) % len(CORES)])
        d = ImageDraw.Draw(im)
        borda = int(min(w, h) * 0.04)
        d.rounded_rectangle((borda, borda, w - borda, h - borda), radius=borda, outline="white", width=max(4, borda // 5))
        cy = int(h * 0.80)
        d.text((w / 2, cy), str(k), font=grande, fill="white", anchor="mm")
        d.text((w / 2, cy + int(min(w, h) * 0.17)), "FOTO OU CLIPE", font=pequena, fill="white", anchor="mm")
        p = pasta / f"cartao-{k:02d}.png"
        im.save(p)
        feitos.append(p)
    return feitos


def lugares(modelo: dict) -> int:
    return sum(v.get("repetir", 1) for v in modelo["vagas"])


FORMATOS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


MIDIAS_OK = {".mp4", ".mov", ".jpg", ".jpeg", ".png"}


def midias_da_pasta(pasta: Path) -> list[str]:
    """As mídias de `<midias>/<id>/`. Com um `ordem.txt` ali, valem a ordem e o ponto de entrada dele
    (uma por linha, `arquivo.mp4` ou `arquivo.mp4@2.5`; `#` comenta); sem ele, todas em ordem de nome."""
    ordem = pasta / "ordem.txt"
    if not ordem.is_file():
        return [str(p) for p in sorted(pasta.iterdir()) if p.suffix.lower() in MIDIAS_OK]
    saida = []
    for linha in ordem.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        nome, _, de = linha.partition("@")
        if not (pasta / nome).is_file():
            raise SystemExit(f"{ordem}: {nome} não está na pasta")
        saida.append(str(pasta / nome) + (f"@{de}" if de else ""))
    return saida


def exemplo(modelo_p: Path, saida: Path, kit: Path, musica_p: Path, midias: Path | None = None) -> Path:
    modelo = json.loads(modelo_p.read_text(encoding="utf-8"))
    mid = modelo_p.stem
    projeto = saida / "projetos" / mid
    edit = projeto / "edit"
    # com `<midias>/<id>/` (clipes grátis do buscar_mixkit.py), eles entram na ordem; sem, os cartões
    pasta = midias / mid if midias else None
    proprias = midias_da_pasta(pasta) if pasta and pasta.is_dir() else []
    cards = proprias or [str(p) for p in cartoes(projeto / "cartoes", lugares(modelo), FORMATOS[modelo.get("formato", "9:16")])]
    with tempfile.TemporaryDirectory() as casa:  # o kit não mexe na lista de projetos de ninguém
        env = {**os.environ, "CUTMIND_HOME": casa}
        cmd = ["uv", "run", "--project", str(kit), "python", "-X", "utf8", str(kit / "helpers" / "montagem.py"),
               "usar", str(modelo_p), "--musica", str(musica_p), "--midias", *cards,
               "--edit", str(edit), "--substituir"]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (projeto / "usar.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    final = edit / "final.mp4"
    if r.returncode != 0 or not final.is_file():
        raise SystemExit(f"{mid}: a montagem falhou (veja {projeto / 'usar.log'})")
    destino = saida / f"{mid}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(final), "-vf", "scale=720:-2:flags=lanczos",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", "128k", str(destino)], check=True)
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modelos", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--kit", type=Path, required=True)
    ap.add_argument("--so", default=None, help="só o modelo com este id")
    ap.add_argument("--midias", type=Path, default=None, help="pasta com uma subpasta de clipes ou fotos por modelo")
    a = ap.parse_args()
    a.saida.mkdir(parents=True, exist_ok=True)
    musica_p = a.saida / "batida-do-exemplo.wav"
    dur = musica(musica_p)
    print(f"batida: {musica_p.name} ({dur:.1f} s, {BPM} BPM, drop no compasso {CALMOS + 1})")
    for p in sorted(a.modelos.glob("*.json")):
        if a.so and p.stem != a.so:
            continue
        print(f"{p.stem}: montando...", flush=True)
        d = exemplo(p, a.saida.resolve(), a.kit.resolve(), musica_p.resolve(), a.midias.resolve() if a.midias else None)
        print(f"{p.stem}: {d.name} ({d.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
