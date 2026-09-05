# to8-soundfx-generator

Génère les données `soundFX` du moteur Thomson TO8 (`engine/sound/soundFX.asm`,
driver YM2413) à partir d'un fichier audio **ou** de paramètres de synthèse, avec
un preview à l'oreille avant de builder le jeu.

---

## Ce que c'est, et ce que ce n'est pas

Le format cible n'est pas un sampler : c'est un **séquenceur de registres sur une
seule voie FM**. Un bruitage est une liste d'écritures dans les registres du
YM2413, chacune suivie d'un délai en ticks 50 Hz.

Ce qui en découle, et qu'aucun outil ne pourra contourner :

| Contrainte | Conséquence |
|---|---|
| grille de 20 ms (IRQ 50 Hz) | toute transitoire plus rapide disparaît |
| une seule voie, monophonique | ni accord, ni couche, ni réverbération |
| pas de générateur de bruit sur la voie mélodique | **une explosion enregistrée ne se convertit pas** |
| volume sur 4 bits | 16 crans de 3 dB, soit 45 dB de dynamique |
| 15 instruments figés en ROM | le timbre s'approche, il ne se reproduit pas |
| compteur de commandes sur 1 octet | **255 commandes maximum**, ~2,5 s |

Les sons qui passent bien : lasers, jingles de bonus, power-ups, alarmes,
sirènes, montées de moteur — tout ce qui est **tenu et balayé**.
Pour les explosions et les impacts, utiliser le **mode paramétrique** : un
balayage descendant avec du jitter donne un bien meilleur résultat que l'analyse
d'un enregistrement.

---

## Installation

```sh
./build.sh          # compile emu2413 + le shim (cc requis)
```

Dépendances : **Python 3.10+**, **numpy**, **ffmpeg**, un compilateur C. Rien
d'autre.

Tout ce que ffmpeg sait lire est accepté tel quel — wav, mp3, flac, aiff, mais
aussi **mp4/mov** : inutile d'extraire la piste audio à la main, l'outil la
décode et la convertit en mono 44,1 kHz au chargement. Pour extraire quand même :
`ffmpeg -i video.mp4 -vn -ac 1 -ar 44100 son.wav`.

---

## Utilisation

### Interface (avec preview)

```sh
./run.sh            # ouvre http://127.0.0.1:8731/
```

Deux onglets — **Paramétrique** et **Fichier audio** — les courbes de hauteur et
de volume tracées, un bouton **Rendu TO8** et un bouton **Source** pour l'A/B, et
le bloc assembleur prêt à copier. Tout se régénère en direct quand on bouge un
réglage.

**Sélection dans la source.** En mode fichier, la forme d'onde s'affiche avec deux
poignées : glisser sur l'onde pour tracer une sélection, ou attraper un marqueur
pour l'ajuster. Seule la sélection est convertie — pratique pour isoler un bruit
au milieu d'un enregistrement, et pour rester sous les 255 commandes. Les bornes
sont **calées sur la grille de 20 ms** du driver, et l'écran affiche le nombre de
trames que ça représente. Le bouton *caler sur le son* pose les marqueurs sur la
partie où une hauteur est détectée, *tout sélectionner* revient au fichier
entier ; les deux champs numériques servent au réglage fin. Le bouton **Source**
ne rejoue que la sélection, pour que l'A/B compare bien la même chose.

Le preview est amplifié ×8 : une voie seule ne pèse qu'un neuvième du plein de la
puce. Le gain est **fixe**, donc deux bruitages gardent entre eux le rapport de
niveau qu'ils auront dans le jeu.

### Ligne de commande

```sh
./cli.py presets
./cli.py sweep --preset explosion --name Explosion --channel 4 -o son.asm --wav preview.wav
./cli.py wav laser.wav --name Laser --channel 4 --auto-instrument -o son.asm
./cli.py wav prise.wav --start-ms 1200 --end-ms 1800 --name Impact -o son.asm
./cli.py wav laser.wav --interleave --switch-penalty 0.5 -o son.asm
./cli.py import ../../.../r-type/objects/soundFX/soundFX.asm soundFX.FireSound.data --wav rtype.wav
```

`import` relit un bloc existant : c'est ce qui a servi à valider le générateur
contre les six bruitages de r-type.

---

## Intégrer le résultat dans un jeu

Le bloc généré va dans `objects/soundFX/soundFX.asm`, et il faut **deux ajouts
cohérents entre eux** :

```asm
soundFX.soundTable
            fdb     soundFX.Explosion.data     ; <- meme ordre...
```
```asm
; objects/soundFX/soundFX.const.asm
soundFX.Explosion equ 0                        ; <- ...que les ids
```

Puis dans l'objet qui doit sonner :

```asm
        INCLUDE "./objects/soundFX/soundFX.const.asm"
        INCLUDE "./engine/sound/soundFX.macro.asm"
        ...
        _soundFX.play soundFX.Explosion,1
```

Voir `battlesquadron/docs/etude-bruitages-soundfx.md` pour le câblage complet
(objet paginé, variables résidentes, tick dans `UserIRQ`).

### Le choix de la voie

Sur battlesquadron, la musique occupe les deux puces. Mesure sur les VGM du
projet : le SN76489 est plein, le YM2413 tourne en mode rythme (voies 6-8 =
batterie) et le thème in-game n'utilise pas la **voie 4**. C'est le défaut de
l'outil. Pour un autre jeu, refaire la mesure.

---

## Mode mélodique

Pour un jingle de bonus, un power-up, un arpège — tout ce qui doit sonner
**juste**. La courbe de hauteur brute ondule (vibrato, portamento, hésitations
du détecteur) et le résultat glisse ou sonne faux. Le mode mélodique découpe le
son en **notes tenues** et cale chacune sur un demi-tempéré.

Trois choses le rendent utilisable sur de vraies prises :

- **Le découpage en notes**, pas le snap image par image. Snapper chaque trame
  fait papillonner la note entre deux demi-tons dès que la hauteur passe près
  d'une frontière ; on regroupe donc en segments stables et on prend la médiane
  de chacun. Une durée minimale de note (réglable) absorbe les scories de bord,
  mais **uniquement** vers une note voisine réellement stable — sinon un
  glissando se ferait manger et se réduirait à sa médiane.
- **La compensation d'accordage.** Une prise tombe rarement sur le la 440. Le
  décalage est mesuré par médiane *dans* chaque note (contre le vibrato) puis
  moyenne circulaire *entre* les notes (contre l'enroulement à ±50 cents) — les
  deux pièges se compensent mutuellement si on ne traite qu'un seul. Une
  confiance est calculée et affichée : quand elle chute (vibrato supérieur au
  demi-ton, source pile entre deux notes), l'outil le dit au lieu de compenser
  au hasard, et on règle l'accordage à la main.
- **La ré-attaque.** À chaque début de note, le key-on repasse par zéro pour que
  l'enveloppe reparte — sinon les notes s'enchaînent en legato. Coûte 3 octets
  par note, désactivable.

Effet de bord très appréciable : une note tenue devient **une commande avec un
long délai** au lieu d'une par trame. Sur un jingle de 4 notes analysé depuis un
wav, mesuré : **214 → 85 octets**.

Une gamme peut être forcée (majeure, mineure, pentatoniques, blues). Ça change
la mélodie, mais ça la rend toujours juste — utile pour un jingle vite fait.

```sh
./cli.py wav jingle.wav --melodic --name Bonus -o son.asm
./cli.py wav jingle.wav --melodic --min-note-frames 5 --no-retrigger -o son.asm
./cli.py wav jingle.wav --melodic --tuning-cents 0 --scale penta-mineure --root 9
```

---

## Instrument custom : à manier avec précaution

L'option existe (`--custom`, ou la case dans l'interface) et fait un ajustement
local des 8 octets du patch pour se rapprocher de la source. Elle émet la
commande `$FF` du driver.

**Les registres `$00`-`$07` sont globaux à la puce.** Si la musique du jeu
utilise l'instrument custom — c'est le cas de battlesquadron, la voie 5 du thème
in-game le sélectionne — un bruitage qui y touche casse son timbre pour tout le
niveau. L'option est donc **désactivée par défaut**, et l'interface le rappelle.

---

## Validation

`python3 -m tests` (9 tests) vérifie, contre l'émulateur :

- la formule `f = fnum × clk / 72 / 2^(19−block)` — écart max mesuré **0,02 %** ;
- le pas de volume à **3,01 dB** par cran ;
- que le jeu de patchs chargé est bien celui du YM2413 ;
- que les notes sont retrouvées à travers ±45 cents de vibrato ;
- qu'une source désaccordée de 40 cents donne les mêmes notes ;
- que la ré-attaque relance bien l'enveloppe (mesuré : ×2,66 au passage de note,
  contre ×0,94 en legato) ;
- qu'un glissando reste une suite de notes au lieu d'être écrasé en une seule.

Les six bruitages de r-type, relus par `import`, redonnent **exactement** les
tailles mesurées par lwasm (76, 118, 130, 130, 115, 199 = 768 octets).

**Limite mesurée du mode mélodique** : au-delà d'environ 45 cents de vibrato,
une note couvre plus d'un demi-ton et devient réellement ambiguë — aucun
estimateur ne peut trancher. L'outil le signale par la confiance d'accordage
plutôt que de deviner.

**Réserve connue** : les patchs ROM d'emu2413 (relevés sur puce) et la table en
commentaire de `engine/sound/soundFX.asm` (ancienne table de la doc) diffèrent
d'un quartet sur 9 instruments. Aucun impact sur le jeu — le driver n'écrit jamais
de patch sauf commande `$FF` explicite — mais la fidélité du preview dépend de
laquelle est juste sur la vraie carte son.

---

## Organisation

```
build.sh  run.sh  cli.py
to8sfx/
  opll.py         emulateur (ctypes), patchs ROM, conversions hauteur/volume
  analyze.py      chargement audio, YIN, enveloppe, voisement -> trames 50 Hz
  parametric.py   balayages et presets
  melody.py       decoupage en notes, accordage, gammes, re-attaque
  instruments.py  appariement spectral, Viterbi d'entrelacement, fit du patch custom
  codegen.py      trames -> commandes (deduplication/RLE) -> assembleur
  importer.py     relecture d'un bloc existant, ecriture wav
  server.py       interface web locale (stdlib)
static/index.html
vendor/emu2413/   emulateur OPLL de Mitsutaka Okazaki (MIT)
tests/
```

emu2413 est sous licence MIT, voir `vendor/emu2413/LICENSE`.
