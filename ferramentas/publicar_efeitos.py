"""Publica filtros e transições na biblioteca do kit: confere os zips, sobe e atualiza o catálogo.

A pasta de entrada tem os pacotes já no formato do kit, um zip por efeito, com o nome do
arquivo igual ao id (`f-abracos-macios.zip`). Cada zip traz o `efeito.json` (formato, tipo,
motor, nome e, na transição, `duracao_ms`); é dele que saem o tipo, o nome e a duração do
catálogo.

Para cada zip, as mesmas travas que o kit aplica ao abrir (`helpers/pacotes.py`): nomes
sem pasta, sem repetição ignorando maiúsculas, até 200 arquivos e 256 MB, `efeito.json`
com formato 1 e tipo filtro ou transição.

Depois:
- sobe para a Release `--release` deste repositório, em blocos, e confere tamanho e sha256
  no GitHub;
- regrava o `catalogo.json` da raiz (o mesmo id é trocado, o resto fica);
- sobe o catálogo para a Release `catalogo` (o kit pega com `pacotes.py atualizar`);
- com `--kit`, copia o catálogo também para `<kit>/assets/pacotes/catalogo.json`.

`--local <pasta>` não sobe nada: monta a mesma árvore da Release numa pasta, para testar.

uso: python -X utf8 ferramentas/publicar_efeitos.py <pasta> --release efeitos-1 [--kit <raiz do kit>] [--local <pasta>]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from publicar_trilhas import BASE, RAIZ, REPO, _ID, gh, sha256

TIPOS = {"filtro", "transicao"}
BLOCO = 40  # arquivos por chamada de upload: a linha de comando do Windows tem limite


def ler_pacote(zp: Path) -> dict:
    with zipfile.ZipFile(zp) as z:
        info = z.infolist()
        nomes = [i.filename for i in info]
        assert len(info) <= 200 and sum(i.file_size for i in info) <= 256 * 1024 * 1024, f"{zp.name}: grande demais"
        assert not any("/" in n or "\\" in n or n.startswith(".") for n in nomes), f"{zp.name}: nome com pasta"
        assert len({n.lower() for n in nomes}) == len(nomes), f"{zp.name}: nomes repetidos"
        man = json.loads(z.read("efeito.json"))
    assert man.get("formato") == 1 and man.get("tipo") in TIPOS, f"{zp.name}: efeito.json inválido"
    assert isinstance(man.get("nome"), str) and man["nome"].strip(), f"{zp.name}: sem nome"
    return man


def subir(release: str, arquivos: list[Path], titulo: str) -> None:
    if subprocess.run(["gh", "release", "view", release, "-R", REPO], capture_output=True).returncode != 0:
        gh("release", "create", release, "-R", REPO, "--title", titulo, "--notes", "Pacotes do kit. Ver o catalogo.json.")
    for i in range(0, len(arquivos), BLOCO):
        gh("release", "upload", release, *map(str, arquivos[i:i + BLOCO]), "-R", REPO, "--clobber")
        print(f"  enviados {min(i + BLOCO, len(arquivos))}/{len(arquivos)}", flush=True)
    rid = json.loads(gh("api", f"repos/{REPO}/releases/tags/{release}").stdout)["id"]
    no_github, pagina = {}, 1
    while True:  # a API devolve os anexos em páginas de no máximo 100
        r = json.loads(gh("api", f"repos/{REPO}/releases/{rid}/assets?per_page=100&page={pagina}").stdout)
        if not r:
            break
        no_github.update({a["name"]: a for a in r})
        pagina += 1
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
    cat_p = (a.local / "catalogo" / "catalogo.json") if a.local else RAIZ / "catalogo.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8")) if cat_p.is_file() else {
        "versao": 1, "repo": REPO, "base": BASE, "pacotes": []}
    novos, arquivos = [], sorted(a.pasta.glob("*.zip"))
    for zp in arquivos:
        pid = zp.stem
        assert _ID.fullmatch(pid), f"id inválido: {pid}"
        man = ler_pacote(zp)
        dur = round(man.get("duracao_ms", 0) / 1000, 3) if man["tipo"] == "transicao" else 0.0
        novos.append({"id": pid, "tipo": man["tipo"], "nome": man["nome"].strip()[:80], "clima": "", "tags": [],
                      "duracao": dur, "release": a.release, "arquivo": zp.name,
                      "tamanho": zp.stat().st_size, "sha256": sha256(zp)})
    print(f"{len(novos)} pacotes conferidos: {sum(1 for n in novos if n['tipo'] == 'filtro')} filtros, "
          f"{sum(1 for n in novos if n['tipo'] == 'transicao')} transições", flush=True)
    if a.local:
        destino = a.local / a.release
        destino.mkdir(parents=True, exist_ok=True)
        for f in arquivos:
            shutil.copy2(f, destino / f.name)
    else:
        subir(a.release, arquivos, f"Efeitos ({a.release})")
    ids = {n["id"] for n in novos}
    cat["pacotes"] = [p for p in cat["pacotes"] if p["id"] not in ids] + novos
    cat["gerado"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cat_p.parent.mkdir(parents=True, exist_ok=True)
    cat_p.write_bytes((json.dumps(cat, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if not a.local:
        from publicar_trilhas import subir as subir_catalogo
        subir_catalogo("catalogo", [cat_p], "Catálogo")
    if a.kit:
        shutil.copy2(cat_p, a.kit / "assets" / "pacotes" / "catalogo.json")
    print(f"catálogo: {len(cat['pacotes'])} pacote(s), {len(novos)} desta vez → {cat_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
