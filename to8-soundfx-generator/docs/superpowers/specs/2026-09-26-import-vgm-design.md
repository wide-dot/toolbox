# Onglet VGM : transcrire un export DefleMask en bloc soundFX

Date : 2026-09-26

## Le besoin

Composer un bruitage dans DefleMask — un tracker, avec un piano-roll, des
enveloppes et une oreille immédiate — puis l'exporter en `.vgm` et le convertir
en bloc `soundFX` pour le moteur TO8. C'est une troisième voie d'entrée, à côté
de **Créer** (tirage paramétrique) et **Fichier audio** (analyse d'un
enregistrement).

Ce que ça apporte que les deux autres n'ont pas : le VGM porte **les écritures
de registres elles-mêmes**. Il n'y a rien à deviner — ni hauteur à détecter, ni
timbre à apparier. Ce que DefleMask a envoyé à la puce est ce qu'on écrit.

## Contrainte de non-régression

**Les onglets Créer et Fichier audio doivent continuer à fonctionner à
l'identique.** C'est la condition posée par l'auteur du projet. Conséquence
assumée dans tout le design : `design.py`, `codegen.py`, `bank.py`, `analyze.py`
et `melody.py` ne sont pas modifiés. La suite de tests actuelle (77 tests) doit
rester verte, sans qu'on touche à un seul de ses fichiers.

## Décisions de conception

Quatre questions tranchées, chacune ayant réduit la portée :

| Question | Décision | Ce que ça écarte |
|---|---|---|
| VGM multi-voies vs. driver monophonique | **choisir une voie, la sortir seule** | l'écrasement silencieux de 9 voies sur une, que fait le `vgm2sfx` Java |
| budget de 255 commandes | **sélection temporelle à la souris** | la troncature aveugle, la réduction automatique |
| branchement sur le pipeline | **transcription directe en `Command[]`** | le décodage en trames, qui aplatirait les attaques intra-trame |
| entrée dans la banque | **non, bloc à copier seulement** | toute modification de `bank.py` |

### Pourquoi la transcription directe, et pas le modèle Frame

Le modèle `opll.Frame` porte **un état par trame de 20 ms** : hauteur, volume,
instrument, attaque. Le format du driver est plus fin que ça — il accepte un
délai de 0, donc plusieurs écritures dans la même trame. `frames_to_commands`
s'en sert déjà pour écrire instrument, F-Num bas et block+key-on d'affilée.

Passer par `Frame` coûterait donc de l'information que le format sait porter :
le bit sustain, un changement d'instrument en cours de trame, deux écritures de
hauteur dans le même tick. Aller directement aux `Command` est à la fois **plus
fidèle et plus court à écrire**.

Le prix : un VGM importé n'est pas retouchable avec les curseurs de l'onglet
Créer. C'est cohérent avec ce qu'on attend d'un import — on retouche dans
DefleMask et on réexporte.

### Pourquoi pas dans la banque

`BankSound` porte `params: design.SfxParams`, et `Bank.build()` **régénère**
chaque son par `design.render()`. Le docstring de `_bank_import` en fait une
règle : « le JSON porte les paramètres et pas les données rendues — c'est ce qui
rend un son modifiable des semaines plus tard ».

Un son venu d'un VGM n'a pas de `SfxParams`. L'y faire entrer demanderait soit
d'y stocker des données rendues (l'invariant tombe), soit d'y stocker un chemin
de fichier externe (la banque cesse d'être autonome). Les deux ont été écartés :
l'onglet sort un bloc `fcb` à copier, comme le fait déjà l'onglet Fichier audio.

**À dire dans l'aide de l'onglet**, sinon on cherche le bouton : pour mélanger
un bruitage VGM et des créations dans un `soundFX.asm` généré d'un coup, il faut
coller le bloc à la main et ajouter son `fdb` dans `soundFX.soundTable` et son
`equ` dans `soundFX.const.asm`.

## Architecture

### `to8sfx/vgm.py` — nouveau module

Le pendant de `importer.py`. Celui-ci relit de l'assembleur, celui-là relit du
VGM ; tous deux rendent des `codegen.Command`. Aucune dépendance au reste du
paquet en dehors de `codegen.Command` et `opll`.

```python
@dataclass
class VgmFile:
    writes: list[tuple[int, int, int]]  # (tick 50 Hz, registre, donnée)
    n_ticks: int
    clock: int
    has_rhythm: bool                    # le VGM écrit-il $0E avec le bit RHYTHM_ON

@dataclass
class ChannelInfo:
    channel: int
    writes: int
    first_tick: int
    last_tick: int
    instruments: list[int]              # numéros d'instrument employés
    uses_custom: bool                   # emploie l'instrument 0

parse(data: bytes) -> VgmFile
survey(v: VgmFile) -> list[ChannelInfo]
to_commands(v, src_channel, t0, t1) -> (list[Command], warnings)
trace(v, src_channel, t0, t1) -> list[dict]   # hauteur/volume/key-on par tick
```

#### `parse`

- `.vgz` : si les deux premiers octets sont `1F 8B`, décompresser par `gzip`.
- En-tête : identifiant `Vgm ` à 0, version à `0x08`, horloge YM2413 à `0x10`,
  offset des données à `0x34`. Les données commencent à `0x40` si la version est
  antérieure à 1.50 ou si l'offset est nul, sinon à `0x34 + offset`. Vérifié sur
  les fichiers du dépôt : v1.50 → `0x40`, v1.61 → `0x100`.
- Horloge YM2413 nulle → erreur explicite nommant la puce trouvée, parce que le
  cas réel est un export SN76489 (`music/TO-001.vgm`) ou YM2612, et que le
  message doit dire quoi changer dans DefleMask.
- Opcodes traités : `0x51` (écriture YM2413), `0x61/0x62/0x63` et `0x70-0x7F`
  (attentes), `0x66` (fin), `0x67` (bloc de données, sauté selon sa taille),
  `0x4F/0x50` et `0x52-0x5F` (autres puces, sautés), `0x80-0x8F`, `0x90-0x95`,
  `0xE0`. Un opcode inconnu lève une erreur nommant sa position — silencieux,
  il désynchroniserait tout le flux qui suit.

#### Le tick, et le piège des 60 Hz

Le VGM compte le temps en **samples à 44 100 Hz**. Le driver compte en **ticks
de 20 ms**. On cumule les samples et on divise par 882 **en reportant le
reste** :

```
cumul += attente
ticks_ecoules = cumul // 882
cumul = cumul % 882
```

C'est la règle du `vgm2sfx` Java, et elle a une conséquence qui mérite d'être
dite : un VGM exporté par DefleMask en **60 Hz** (attentes de 735 samples,
opcode `0x62`) garde sa **durée réelle en secondes**. Compter une attente pour
un tick, au lieu de diviser par 882, étirerait le bruitage de 20 %.

#### `to_commands` — cinq étapes, dans cet ordre

1. **Filtrer.** Les registres `$10-$38` dont `reg & 0x0F == src_channel`, plus
   `$00-$07` (le patch custom, global à la puce).

2. **Amorcer.** L'état des registres de la voie *tel qu'il est à `t0`* est
   réémis en tête, avec un délai de 0. Sans ça, une sélection qui démarre au
   milieu d'une note joue avec un état arbitraire — et c'est le cas normal,
   puisque découper est l'usage même de la sélection.

3. **Rebaser le registre.** `reg & 0xF0`. Le driver **ajoute** le numéro de voie
   de sortie aux registres au-dessus de `$0F` : un `$12` lu sur la voie 2 doit
   partir en `$10` pour que la puce reçoive `$10 + voie_de_sortie`. C'est la
   sémantique de `Command.reg`, et c'est ce que le test d'aller-retour vérifie.

4. **Dédupliquer.** Une écriture qui ne change pas la valeur courante du
   registre est sautée. Sans cette étape les 6 643 écritures de la voie 2 de
   `ingame-YM2413.vgm` restent 6 643 — le budget est de 255.

5. **Délais.** Le délai d'une commande est le nombre de ticks jusqu'à l'écriture
   suivante. Au-delà de 255 (le champ tient sur un octet), on scinde en
   réémettant `$10` à l'identique : la ruse est déjà dans `frames_to_commands`,
   elle est inoffensive et relance 255 ticks.

#### Patch custom

Si la voie sélectionne l'instrument 0, le son dépend des registres globaux
`$00-$07`. On préfixe alors la commande `$FF` avec leur état à `t0`.
`codegen.to_asm` sait déjà écrire l'étiquette de patch **et** l'avertissement
sur leur globalité.

Mais `to_asm` n'écrit **qu'une seule** étiquette de patch : tous ses `fdb`
pointent le premier. Donc si `$00-$07` change **pendant** la fenêtre, on
avertit, au lieu de produire un bloc silencieusement faux. (Corriger `to_asm`
pour plusieurs patchs serait une modification de `codegen.py`, hors de la
contrainte de non-régression, et le cas ne se présente pas pour un bruitage
court.)

#### Avertissements rendus au client

- le VGM écrit la section rythme : ces écritures sont ignorées (décision 4) ;
- la voie choisie est 6, 7 ou 8 alors que le rythme est actif : la puce les a
  réquisitionnées, la voie est **muette**, pas approximative ;
- plus de 255 commandes : la fenêtre est trop large ;
- `$00-$07` change pendant la fenêtre ;
- la voie choisie n'a aucune écriture dans la fenêtre.

### Serveur — deux points d'entrée

Sur le modèle exact de `_listen`, qui fait déjà commandes → `stats` →
`commands_to_events` → `opll.render` → `importer.wav_bytes` → URL de preview.

- `POST /api/vgm/upload` — le fichier. Retourne `{name, n_ticks, seconds,
  clock, channels[], warnings}`. Stocké dans `STATE["vgm"]`.
- `POST /api/vgm/render` — `{src_channel, start_frame, end_frame, out_channel,
  name}`. Retourne `{asm, stats, preview, trace, warnings}`.

`trace` porte, par tick, hauteur en Hz / volume / key-on de la voie choisie,
reconstruits par relecture d'état. C'est ce qui permet de **voir** la voie avant
de la découper.

### Interface — 3e onglet, à côté de « Fichier audio »

Zone de dépôt (`.vgm`/`.vgz`) → liste des voies avec leur activité et les
instruments employés (« voie 2 — 6 643 écritures, Trumpet ») → un clic
sélectionne → le tracé de la voie s'affiche sur toute la durée, avec **les deux
poignées de sélection réutilisées de l'onglet Fichier audio** → compteur
commandes / octets / secondes en direct, rouge au-delà de 255 → nom et voie de
sortie.

`Rendu TO8` et `Copier l'assembleur` sont déjà communs aux onglets.

Le basculement d'onglet suit le mécanisme en place (`mode`, `classList`), et
doit **masquer les panneaux propres aux deux autres modes** comme ils le font
déjà entre eux.

### Ligne de commande

```sh
./cli.py vgm son.vgm --survey
./cli.py vgm son.vgm --channel 2 --from-frame 40 --to-frame 90 \
         --name Laser --out-channel 4 -o son.asm --wav preview.wav
```

## Tests — `tests/test_vgm.py`

VGM **construits dans le test**, pour ne dépendre d'aucun fichier hors dépôt.
Un test de fumée sur `rtype-YM2413.vgm` est **gardé par l'existence du
fichier**, et sauté sinon.

- en-tête v1.50 (données à `0x40`) et v1.61 (à `0x100`) ; `.vgz` gzippé ;
- horloge YM2413 nulle → erreur nommant la puce trouvée ;
- timing : une suite de `0x62` (60 Hz) et une de `0x63` (50 Hz) rendent la même
  **durée en secondes** ; le report du reste est vérifié sur des attentes qui ne
  tombent pas juste, pas seulement la division ;
- filtrage : VGM à deux voies, seule la voie demandée ressort, registres rebasés
  sur `$10/$20/$30` ;
- amorçage : fenêtre démarrant après un key-on → l'état est réémis en tête ;
- déduplication : une valeur réécrite à l'identique n'ajoute pas de commande ;
- délai supérieur à 255 → scission, **et la durée totale en ticks conservée** ;
- patch : instrument 0 → commande `$FF` avec le bon patch ; patch changé en
  cours de fenêtre → avertissement ;
- **aller-retour** : `codegen.to_asm` puis `importer.parse_asm_sound` redonnent
  les mêmes commandes. C'est le test qui attrape une erreur de rebasage ;
- rythme actif → avertissement ; voie 7 avec rythme actif → avertissement de
  voie muette ;
- opcode inconnu → erreur nommant sa position.

Ajouter le module à la liste de `tests/__main__.py`.

## Non-régression, vérifiée explicitement

- `python3 -m tests` : 77 tests OK avant, et les 77 mêmes OK après, plus les
  nouveaux ;
- aucun fichier de test existant modifié ;
- `design.py`, `codegen.py`, `bank.py`, `analyze.py`, `melody.py`,
  `instruments.py`, `rhythm.py`, `opll.py`, `importer.py` inchangés ;
- les deux onglets existants exercés à la main dans l'interface après coup.

## Hors portée

- entrée dans la banque (décision 4) ;
- transcription de la section rythme (décision 4) ;
- plusieurs voies en un seul bruitage, ou un bruitage par voie (décision 1) ;
- retouche paramétrique d'un VGM importé (décision 3) ;
- les autres puces d'un VGM (SN76489, YM2612) : refusées avec un message qui
  nomme la puce trouvée.
