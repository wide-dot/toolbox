# to8-soundfx-generator

Atelier de création des bruitages `soundFX` du moteur Thomson TO8
(`engine/sound/soundFX.asm`, driver YM2413) : catégories d'événements de jeu,
tirage au sort, mutation à cadenas, trois couches de synthèse (ton, arpège,
bruit), et une banque qui écrit d'un coup les deux fichiers assembleur
cohérents entre eux. L'analyse d'un fichier audio existant reste disponible
dans son propre onglet, mais ce n'est plus le point d'entrée principal.

---

## Ce que c'est, et ce que ce n'est pas

Le format cible n'est pas un sampler : c'est un **séquenceur de registres sur une
seule voie FM**. Un bruitage est une liste d'écritures dans les registres du
YM2413, chacune suivie d'un délai en ticks 50 Hz. L'outil ne demande donc pas
« quel fichier convertir » mais « quel événement doit sonner » : on choisit une
catégorie (tir, explosion, impact, ramassage, saut, dégât, menu, alarme), on
tire un son au sort dedans, on le mute par petites touches en verrouillant ce
qui est déjà bon, et on le range dans une banque qui devient directement le
`soundFX.asm` du jeu.

Ce qui découle du format, et qu'aucun outil ne pourra contourner :

| Contrainte | Conséquence |
|---|---|
| grille de 20 ms (IRQ 50 Hz) | toute transitoire plus rapide disparaît |
| une seule voie, monophonique | ni accord, ni couche, ni réverbération |
| la voie mélodique ne génère pas de bruit | mais la puce en fait par ailleurs : voir **Couche bruit** ci-dessous |
| volume sur 4 bits | 16 crans de 3 dB, soit 45 dB de dynamique |
| 15 instruments figés en ROM | le timbre s'approche, il ne se reproduit pas |
| compteur de commandes sur 1 octet | **255 commandes maximum**, ~2,5 s |

Les sons qui passent bien à l'oreille et au budget : lasers, jingles de bonus,
power-ups, alarmes, sirènes, montées de moteur — tout ce qui est **tenu et
balayé**. Pour les explosions et les impacts, la couche bruit (section rythme
du YM2413, voir plus bas) donne un bien meilleur résultat que l'analyse d'un
enregistrement, et les huit catégories la préconfigurent déjà où elle a du
sens.

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

Deux onglets — **Créer** et **Fichier audio**.

**Créer** est le point d'entrée principal :

- **Catégorie.** Huit boutons (tir, explosion, impact, ramassage, saut, dégât,
  menu, alarme), chacun avec son propre a priori de plages (enveloppe,
  glissement, jitter, arpège, couche bruit activée ou non par défaut).
- **Tirer au sort.** Une graine tire un jeu de paramètres dans les plages de la
  catégorie choisie, et le rend immédiatement audible.
- **Muter — 8 variantes.** Depuis le son courant, tire 8 variantes à une force
  réglable (curseur en %). Un clic joue une variante, un second clic l'adopte.
  **Le cadenas** à côté de chaque réglage empêche la mutation d'y toucher :
  on fige ce qui est bon et on relance le hasard sur le reste — c'est la seule
  forme d'historique de l'outil, il n'y a pas de pile de tirages rechargeable.
- **Affiner.** Les curseurs des trois couches (enveloppe et glissement pour le
  ton, marches pour l'arpège, activation et kit pour le bruit) en accès direct.
- **Banque.** Nom du son, voie YM2413 (vide = voie par défaut de la banque),
  bouton **Garder dans la banque** ; la liste en dessous affiche pour chaque
  son gardé sa voie, son nombre de commandes, ses octets et un avertissement
  s'il dépasse le budget ou utilise une voie interdite à la couche bruit.

**Fichier audio** garde l'analyse d'un enregistrement : la forme d'onde, la
sélection à la souris, le mode mélodique, le bouton **Générer** et la case
*régénérer en direct*. Voir plus bas. C'est là que le bouton **Source** sert à
comparer le rendu TO8 à l'enregistrement d'origine.

Le bouton **Rendu TO8** (rejouer le dernier son généré, dans les deux onglets)
et le bloc assembleur prêt à copier (**Copier l'assembleur**) sont communs aux
deux modes. La barre latérale reste en revanche partagée sans être filtrée par
onglet : rester sur les contrôles propres à **Créer** (catégorie, tirage,
mutation, affiner, banque) évite d'aller titiller les réglages du mode fichier
audio (instrument, mélodique, nom/voie de sortie), qui appellent le point
d'entrée `/api/generate` et ne s'appliquent qu'en mode **Fichier audio**.

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
./cli.py create --category explosion --seed 42 --name Explosion --channel 4 -o son.asm --wav preview.wav
./cli.py bank banque.json --out-dir objects/soundFX/          # les deux .asm de la banque
./cli.py wav laser.wav --name Laser --channel 4 --auto-instrument -o son.asm
./cli.py wav prise.wav --start-ms 1200 --end-ms 1800 --name Impact -o son.asm
./cli.py wav laser.wav --interleave --switch-penalty 0.5 -o son.asm
./cli.py import ../../.../r-type/objects/soundFX/soundFX.asm soundFX.FireSound.data --wav rtype.wav
```

`create` tire un bruitage au sort dans une catégorie (`tir`, `explosion`,
`impact`, `ramassage`, `saut`, `degat`, `menu`, `alarme` — voir
`to8sfx.design.CATEGORIES`) et écrit son bloc assembleur, comme un tirage isolé
de l'onglet Créer.

`bank` prend un fichier JSON décrivant une banque — `{"name", "default_channel",
"sounds": [{"name", "category", "channel", "priority", "params"}, ...]}`, le
même format que produit `Bank.to_json()` — et écrit `soundFX.asm` et
`soundFX.const.asm` dans `--out-dir`, avec table et identifiants dans le même
ordre. C'est la seule commande qui sait produire les deux fichiers cohérents
d'un coup ; l'interface construit la banque interactivement mais ne les écrit
pas elle-même sur disque.

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

## Couche bruit

La voie mélodique du YM2413 ne sait produire qu'un son pur (une somme
d'harmoniques figée par l'instrument) : rien dans ses registres $10-$36 ne
génère du bruit. Mais la puce, elle, en fait — par un autre chemin. Le registre
$0E porte un **mode rythme** qui reconfigure les voies 6, 7 et 8 en cinq
percussions (grosse caisse, caisse claire, charleston, cymbale, tom), et deux
d'entre elles — caisse claire et charleston — sont bâties sur un générateur de
bruit matériel. C'est la seule source de bruit de toute la puce, et l'outil
s'en sert comme troisième couche de synthèse (`noise_on`, `noise_kit`,
`noise_hits`, `noise_pitch`, `noise_vol` dans `to8sfx.design.SfxParams`,
implémentée dans `to8sfx/rhythm.py`).

Mesuré sur l'émulateur (platitude spectrale : 1 = bruit blanc, 0 = son pur) :

| Source | Platitude spectrale |
|---|---|
| caisse claire (SD) | 0,26 |
| charleston (HH) | 0,12 |
| note mélodique (voie normale) | 0,00 |

**Le prix : les voies 6, 7 et 8 sont réquisitionnées, pas seulement partagées.**
Activer le mode rythme reconfigure ces trois voies pour la batterie ; une
couche mélodique qui y était posée n'est pas dégradée, elle est **effacée**.
Mesuré : RMS identique bit pour bit sur les voies 0 à 5, qu'on active le mode
rythme ou non ; sur les voies 6 et 8, RMS exactement nul dès qu'il s'active,
et quasi nul (résiduel) sur la 7. C'est pour ça que la couche bruit borne les
voies utilisables à **0-5** (`rhythm.MAX_CHANNEL = 5`) et refuse toute banque
qui combine `noise_on` avec une voie 6, 7 ou 8 (`bank.Bank.build` lève, voir
`test_noise_layer_refuses_a_channel_above_six`). Et parce que le registre $0E
est global à la puce, un bruitage qui active le mode rythme écrase l'état de
batterie de la musique en cours pendant toute sa durée — d'où l'avertissement
inséré automatiquement dans le bloc assembleur généré, et le fait que
`noise_on` est **éteint par défaut**.

---

## Mode mélodique

Pour un jingle de bonus, un power-up, un arpège — tout ce qui doit sonner
**juste**. La courbe de hauteur brute ondule (vibrato, portamento, hésitations
du détecteur) et le résultat glisse ou sonne faux. Le mode mélodique découpe le
son en **notes tenues** et cale chacune sur un demi-tempéré.

Quatre choses le rendent utilisable sur de vraies prises :

- **Le découpage en notes**, pas le snap image par image. Snapper chaque trame
  fait papillonner la note entre deux demi-tons dès que la hauteur passe près
  d'une frontière ; on regroupe donc en segments stables et on prend la médiane
  de chacun. Une durée minimale de note (réglable) absorbe les scories de bord,
  mais **uniquement** vers une note voisine réellement stable, et en une seule
  passe sur le découpage d'origine — sinon la cible grossit à chaque
  absorption, devient un aimant, et avale de proche en proche tout un trait
  rapide ou un glissando.
- **Le découpage par l'enveloppe**, et pas seulement par la hauteur. C'est la
  seule information qui sépare quatre doubles croches sur la même note d'une
  note tenue, et la seule qui distingue une vraie note brève d'une hésitation
  du détecteur. Un segment porté par une attaque est gardé même plus court que
  la durée minimale ; le transitoire d'attaque lui-même, où le détecteur se
  trompe souvent d'octave, est rendu à la note qu'il annonce.
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

**Régler la sensibilité aux attaques.** Le seuil (`--onset-db`, curseur dans
l'interface) se règle **au-dessus de la profondeur du trémolo de la source, en
dessous de celle de ses attaques**. Mesuré : à 1,5 dB — le défaut — un trait de
triples croches sort entier et une tenue à 4 dB de trémolo reste d'un bloc ; à
1 dB ce même trémolo se découpe en 8 notes, à 2 dB les triples croches
commencent à se perdre. `0` désactive le découpage par l'enveloppe.

Quand le RMS de la source n'est pas disponible, `melody.quantize` se replie sur
le volume des trames, quantifié par crans de 3 dB ; le seuil y est alors
planché à 4,5 dB, faute de quoi chaque cran passerait pour une attaque. Ce
repli n'est atteint aujourd'hui que par les tests directs de `melody.py` — le
mode mélodique de la ligne de commande et de l'interface passe toujours par
une source audio, donc toujours avec un RMS mesuré.

```sh
./cli.py wav jingle.wav --melodic --name Bonus -o son.asm
./cli.py wav jingle.wav --melodic --min-note-frames 5 --no-retrigger -o son.asm
./cli.py wav jingle.wav --melodic --onset-db 3 -o son.asm   # source qui tremble
./cli.py wav jingle.wav --melodic --tuning-cents 0 --scale penta-mineure --root 9
```

### Sources rapides : ce qu'il faut régler

Un trait où les notes s'enchaînent toutes les 20 à 60 ms est le cas le plus
exigeant, et trois réglages se liguent contre lui par défaut :

| Réglage | Défaut | Pour un trait rapide |
|---|---|---|
| **Lissage** (hauteur) | 1 | laisser à 1 — c'est un filtre médian, il efface les notes plus courtes que sa demi-largeur |
| **Durée mini d'une note** | 3 trames | descendre à 1 quand les notes s'enchaînent vraiment à chaque trame |
| **Sensibilité aux attaques** | 1,5 dB | baisser si les notes se fondent l'une dans l'autre |

Mesuré sur un arpège à **une note toutes les 20 ms** (144 notes en 2,9 s) :
avec les anciens réglages, 47 notes et une alternance de deux hauteurs qui
n'existe pas dans la source ; avec *lissage 1 / durée mini 1*, **144 sur 144**,
motif exact.

Attention en revanche au budget : à une note par trame il faut environ trois
commandes par note, donc **~85 notes, soit 1,7 s** de trait continu avant de
saturer le compteur de l'en-tête. Au-delà, découper la source en plusieurs
bruitages avec les marqueurs.

Un cas voisin, qui n'a rien à voir avec les réglages : quand la source joue
**plusieurs notes à la fois**, il n'y a pas de hauteur unique à trouver. Le
détecteur rend une hauteur de compromis, et la voie du YM2413 étant
monophonique de toute façon, il faut choisir une ligne — arpéger plutôt que
plaquer.

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

`python3 -m tests` (60 tests, dans `tests/test_opll.py`, `test_analyze.py`,
`test_melody.py`, `test_design.py`, `test_rhythm.py`, `test_codegen_noise.py`,
`test_bank.py` et `test_server_design.py`) vérifie, contre l'émulateur, entre
autres :

- la formule `f = fnum × clk / 72 / 2^(19−block)` — écart max mesuré **0,02 %** ;
- le pas de volume à **3,01 dB** par cran ;
- que le jeu de patchs chargé est bien celui du YM2413 ;
- que les notes sont retrouvées à travers ±45 cents de vibrato ;
- qu'une source désaccordée de 40 cents donne les mêmes notes ;
- que la ré-attaque relance bien l'enveloppe (mesuré : ×2,66 au passage de note,
  contre ×0,94 en legato) ;
- qu'un glissando reste une suite de notes au lieu d'être écrasé en une seule ;
- que quatre doubles croches sur la même hauteur restent quatre notes ;
- qu'un trait rapide voisin d'une note tenue n'est pas avalé par elle, même
  avec une erreur d'octave d'une trame sur chaque attaque ;
- mais qu'une erreur d'octave isolée au milieu d'une tenue est toujours
  nettoyée ;
- que le seuil d'attaque par défaut tient les deux bords du compromis ;
- qu'un arpège à une note toutes les 20 ms s'analyse à 100 % de trames voisées,
  avec ou sans bruit — la fenêtre d'analyse était plus longue que les notes, ce
  qui produisait des trous et une hauteur grave absurde tenue sur tout le
  passage ;
- que la plage de fréquences n'a pas été payée en échange : une note à 61,7 Hz
  reste détectée à 100 % ;
- qu'un trait à une note par trame ressort note pour note, à la limite exacte
  de ce que le driver sait représenter ;
- qu'aucune note fantôme au-dessus de `fmax` n'apparaît sur la première trame.

Mesure de bout en bout, sur une mélodie de 16 notes (noires, doubles et triples
croches, plus une note répétée quatre fois) : **10 notes restituées avant, dont
une hauteur jamais jouée ; 16 sur 16 après**, à ±1 trame près — la résolution du
driver — pour **9 octets de plus**.

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

Côté atelier de création, les tests plus récents vérifient en plus, contre
l'émulateur ou par construction :

- que chaque catégorie tire des paramètres dans ses plages déclarées, de façon
  déterministe à graine donnée, et que chacune tient dans le budget de 255
  commandes même à son pire coin de plages ;
- que `mutate` respecte les cadenas (un réglage verrouillé ne bouge jamais) et
  reste dans les bornes globales ;
- que la caisse claire et le charleston sont effectivement bruités (platitude
  spectrale mesurée, voir **Couche bruit**), que la section rythme efface bel
  et bien les voies 6 à 8 sans toucher aux voies 0 à 5, et que `bank.Bank`
  refuse une couche bruit sur une voie hors de cette plage ;
- qu'une banque écrite en JSON puis reconstruite (`Bank.from_json` /
  `Bank.build`) redonne la même table, les mêmes identifiants dans le même
  ordre, et le bon avertissement dans le bloc assembleur pour tout son dont la
  couche bruit est active.

---

## Organisation

```
build.sh  run.sh  cli.py
to8sfx/
  opll.py         emulateur (ctypes), patchs ROM, conversions hauteur/volume
  analyze.py      chargement audio, YIN, enveloppe, voisement -> trames 50 Hz
                  (la fenetre d'integration y vaut une demi-trame : plus longue,
                   elle enjambe les notes breves et les fait disparaitre)
  design.py       modele de son a trois couches (ton/arpege/bruit), CATEGORIES,
                  randomize, mutate a cadenas
  rhythm.py       couche bruit : section rythme du YM2413, MAX_CHANNEL
  bank.py         la banque : JSON <-> soundFX.asm + soundFX.const.asm
  melody.py       decoupage en notes et en attaques, accordage, gammes, re-attaque
  instruments.py  appariement spectral, Viterbi d'entrelacement, fit du patch custom
  codegen.py      trames -> commandes (deduplication/RLE) -> assembleur
  importer.py     relecture d'un bloc existant, ecriture wav
  server.py       interface web locale (stdlib)
static/index.html
vendor/emu2413/   emulateur OPLL de Mitsutaka Okazaki (MIT)
tests/
```

emu2413 est sous licence MIT, voir `vendor/emu2413/LICENSE`.
