# CutMind — pacotes

Efeitos, transições, filtros, trilhas e modelos de montagem do [CutMind](https://github.com/junioralbino28/cutmind), já no formato do kit.

Cada pacote é um arquivo de uma Release deste repositório. O kit não baixa tudo de uma vez: o editor mostra a prévia, e o pacote só desce quando você usa. Os favoritos e os usados por último ficam guardados no seu computador; o resto sai quando o espaço reservado enche.

Quem baixa é o próprio kit, e o catálogo dele diz de onde. Não é preciso baixar nada daqui à mão.

Hoje: 145 filtros e 912 transições, nas Releases `efeitos-1` e `efeitos-2`, e 4 modelos de montagem na Release `montagens-1` (Drop rápido, Fotos com zoom, Antes e depois e Lançamento), cada um com um vídeo de exemplo. O catálogo (`catalogo.json`, também na Release `catalogo`) lista cada um com nome, tipo, tamanho e sha256.

Também 11 efeitos sonoros virais (cha-ching, bong do Taco Bell, notificação do Discord, Dexter, faah e outros) na Release `sons-1`. Eles não entram no `catalogo.json`: a lista vai junto com o kit (`assets/sfx/virais.json`) e o som desce na primeira vez que alguém ouve. São sons de meme, marca e série. Num anúncio pago podem reprovar o anúncio. `ferramentas/publicar_sons.py` publica, a partir de `sons/lista.json`.

As imagens dos vídeos de exemplo são clipes da licença gratuita do Mixkit; `montagens/exemplos/<modelo>/fontes.json` diz de onde veio cada um. A música dos exemplos é uma batida gerada pelas próprias ferramentas daqui.
