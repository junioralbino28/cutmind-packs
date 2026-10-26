"""Publica modelos de montagem na biblioteca do kit: confere, sobe e atualiza o catálogo.

Entrada: a pasta dos modelos (`<id>.json`, o formato do `montagens.py` do kit) e a pasta dos
vídeos de exemplo (`<id>.mp4`, feitos pelo `previa_montagem.py`). Cada modelo passa pela mesma
conferência do kit (`montagens.normalize`); o que o kit recusaria não sai daqui.

No catálogo, cada um vira um pacote `m-<id>` do tipo `montagem`:
- `modelo`: o modelo escrito no próprio catálogo (o painel do kit lista sem baixar nada);
- `arquivo`: o mesmo modelo em JSON na Release (para quem baixar o pacote);
- `previa`: o vídeo de exemplo, que o kit baixa só quando a pessoa toca em ver.

Depois, como os outros: sobe para a Release `--release`, confere tamanho e sha256 no GitHub,
regrava o `catalogo.json`, sobe o catálogo para a Release `catalogo` e, com `--kit`, copia o
catálogo para o kit. `--local <pasta>` não sobe nada: monta a mesma árvore numa pasta, para testar
(o kit aponta para ela com `CUTMIND_PACOTES_BASE`).

Roda com o ambiente do kit:
uso: uv run --project <kit> python -X utf8 ferramentas/publicar_montagens.py <modelos> <exemplos> --kit <kit>
     --release montagens-1 [--local <pasta>] [--copiar-para-o-kit]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from publicar_efeitos import subir
from publicar_trilhas import BASE, RAIZ, REPO, _ID, sha256


def duracao(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    return round(float(r.stdout.strip()), 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modelos", type=Path)
    ap.add_argument("exemplos", type=Path)
    ap.add_argument("--kit", type=Path, required=True)
    ap.add_argument("--release", required=True)
    ap.add_argument("--local", type=Path)
    ap.add_argument("--copiar-para-o-kit", action="store_true", help="copia o catálogo para <kit>/assets/pacotes")
    a = ap.parse_args()
    sys.path.insert(0, str((a.kit / "helpers").resolve()))
    import montagens as mg  # a conferência do kit
    import pacotes as pk

    cat_p = (a.local / "catalogo" / "catalogo.json") if a.local else RAIZ / "catalogo.json"
    base_cat = cat_p if cat_p.is_file() else RAIZ / "catalogo.json"
    cat = json.loads(base_cat.read_text(encoding="utf-8")) if base_cat.is_file() else {
        "versao": 1, "repo": REPO, "base": BASE, "pacotes": []}
    novos, arquivos = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for mp in sorted(a.modelos.glob("*.json")):
            m = mg.normalize(json.loads(mp.read_text(encoding="utf-8")))
            pid = f"m-{mp.stem}"
            assert _ID.fullmatch(pid), f"id inválido: {pid}"
            assert m["id"] == mp.stem, f"{mp.name}: o nome do modelo dá o id {m['id']}, não {mp.stem}"
            video = a.exemplos / f"{mp.stem}.mp4"
            assert video.is_file(), f"{mp.stem}: falta o exemplo {video}"
            modelo = {k: v for k, v in m.items() if k not in ("id", "nome", "criado")}
            arq = Path(tmp) / f"{pid}.json"
            arq.write_bytes((json.dumps({**modelo, "nome": m["nome"]}, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
            previa = Path(tmp) / f"{pid}.mp4"
            shutil.copy2(video, previa)
            novos.append({"id": pid, "tipo": "montagem", "nome": m["nome"], "clima": "", "tags": [],
                          "duracao": duracao(previa), "release": a.release, "arquivo": arq.name,
                          "tamanho": arq.stat().st_size, "sha256": sha256(arq),
                          "previa": {"arquivo": previa.name, "tamanho": previa.stat().st_size, "sha256": sha256(previa)},
                          "modelo": modelo})
            arquivos += [arq, previa]
        print(f"{len(novos)} modelo(s) conferido(s): {', '.join(n['nome'] for n in novos)}", flush=True)
        if a.local:
            destino = a.local / a.release
            destino.mkdir(parents=True, exist_ok=True)
            for f in arquivos:
                shutil.copy2(f, destino / f.name)
        else:
            subir(a.release, arquivos, f"Modelos de montagem ({a.release})")
    ids = {n["id"] for n in novos}
    cat["pacotes"] = [p for p in cat["pacotes"] if p["id"] not in ids] + novos
    cat["gerado"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pk.validar(cat)  # o catálogo inteiro passa na conferência do kit antes de sair daqui
    cat_p.parent.mkdir(parents=True, exist_ok=True)
    cat_p.write_bytes((json.dumps(cat, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if not a.local:
        from publicar_trilhas import subir as subir_catalogo
        subir_catalogo("catalogo", [cat_p], "Catálogo")
    if a.copiar_para_o_kit:
        shutil.copy2(cat_p, a.kit / "assets" / "pacotes" / "catalogo.json")
    print(f"catálogo: {len(cat['pacotes'])} pacote(s), {len(novos)} desta vez → {cat_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
