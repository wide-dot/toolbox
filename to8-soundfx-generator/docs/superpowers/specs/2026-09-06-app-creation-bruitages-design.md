# App de création de bruitages — design

*6 septembre 2026*

## Le problème

L'outil est né du mauvais bout. Il part d'un fichier audio et essaie de le
convertir ; or la cible est un séquenceur de registres à 50 Hz sur **une** voie
FM monophonique. Aucune analyse ne rendra fidèle un enregistrement sur ce
support, et les essais le confirment : le résultat n'est pas convaincant, et il
ne peut pas l'être.

Le mode paramétrique, lui, produit d'emblée des sons utilisables — mais il est
traité en parent pauvre, et il n'offre qu'un balayage de hauteur. Tout ce qu'il
génère se ressemble.

**Ce document redéfinit l'outil comme une app de création**, dont la boucle
centrale est l'exploration par tirage au sort — le modèle sfxr/Bfxr — sur un
espace de paramètres assez riche pour que le tirage soit intéressant.

L'onglet **Fichier audio** est conservé tel quel. Il sera repris plus tard ;
rien dans ce design ne le touche.

## Ce que la puce sait faire

Relevé sur l'émulateur (`vendor/emu2413`), pas sur la documentation.

**Le YM2413 sait faire du bruit.** Le README affirme le contraire : il a tort.
La section rythme (registre `$0E`) offre cinq percussions à base de bruit.
Platitude spectrale mesurée — 1 = bruit blanc, 0 = son pur :

| Source | Platitude | Pic |
|---|---|---|
| caisse claire | 0,267 | 257 Hz |
| charleston | 0,120 | — |
| cymbale | 0,004 | — |
| grosse caisse | 0,000 | 109 Hz |
| note mélodique (référence) | 0,000 | 126 Hz |

**Le driver donne accès à toute la puce.** Dans `engine/sound/soundFX.asm` :

```asm
            cmpa    #$0F
            bls     >                  ; registre <= $0F : ecrit tel quel
            adda    soundFX.currChan   ; sinon on ajoute le numero de voie
```

`$0E` passe donc verbatim depuis n'importe quelle voie. Les registres
d'instrument rythmique (`$16/$26/$36`, `$17/$27/$37`, `$18/$28/$38`) sont
au-dessus de `$0F` et reçoivent le numéro de voie : le générateur **pré-soustrait**
la voie (voie 4 → il émet `$12` pour atteindre `$16`).

**Les couches coexistent.** Une note tenue sur la voie 4 est rigoureusement
inchangée quand le mode rythme s'active (RMS 0,0218 dans les deux cas), et la
frappe s'ajoute par-dessus (0,0542 contre 0,0288 pendant la frappe). Le mode
rythme réquisitionne les voies 6-8, pas la voie mélodique utilisée.

**L'arpège est bon marché.** 84 commandes pour 1 s à une marche par trame,
43 à une marche sur deux — la déduplication de `codegen` mord bien, le registre
`$20` changeant rarement d'une marche à l'autre.

## Le modèle de son

Trois couches entrelacées dans **un seul** flux de commandes.

### Couche TON — voie mélodique

| Paramètre | Plage | Rôle |
|---|---|---|
| `attack_frames` | 0..15 | montée du volume |
| `hold_frames` | 0..40 | palier |
| `decay_frames` | 1..90 | chute |
| `vol_peak` / `vol_end` | 0..15 | 0 = fort |
| `f_start` | 40..5000 Hz | hauteur de départ |
| `slide` | −3..+3 | demi-tons par trame |
| `slide_delta` | −0,2..+0,2 | demi-ton par trame² — l'inflexion du glissement, ce qui donne le « pyoo » qui ralentit |

La hauteur est exprimée **en demi-tons** (`midi0 + slide·t + ½·slide_delta·t²`),
donc en échelle logarithmique. Un choix `exp`/`lin` comme en avait l'ancien mode
paramétrique n'a plus de sens ici : `slide` en demi-tons par trame serait sans
signification sur une interpolation linéaire en hertz. Le champ n'existe pas.
| `vibrato_hz` / `vibrato_cents` | 0..25 / 0..1200 | |
| `jitter_cents` | 0..1200 | substitut de bruit sur la voie mélodique |
| `instrument` | 1..15 | timbre ROM |
| `repeat_frames` | 0..60 | relancer le son entier tous les N (0 = jamais) |

La durée n'est **pas** un paramètre : elle vaut `attack + hold + decay`, bornée
à 127 trames (2,5 s). En faire un réglage indépendant permettrait de la mettre
en contradiction avec l'enveloppe qui la compose.

### Couche ARPÈGE

| Paramètre | Plage | Rôle |
|---|---|---|
| `arp_steps` | jusqu'à 4 valeurs, −24..+24 | demi-tons depuis la hauteur courante |
| `arp_frames` | 0..8 | trames par marche, 0 = éteint |
| `arp_retrigger` | booléen | relancer l'enveloppe à chaque marche |

L'arpège se compose avec le glissement : les marches sont des écarts *relatifs*
à la hauteur du moment. C'est le geste le plus caractéristique du son de puce,
et il est absent de l'outil actuel.

### Couche BRUIT — section rythme

| Paramètre | Plage | Rôle |
|---|---|---|
| `noise_on` | booléen | **faux par défaut**, voir Garde-fous |
| `noise_kit` | sous-ensemble de BD, SD, TOM, CYM, HH | |
| `noise_hits` | 0..40 | nombre de frappes |
| `noise_spread_frames` | 1..90 | étalement de la rafale |
| `noise_accel` | −1..+1 | la densité s'accélère (+) ou retombe (−) |
| `noise_pitch` | 0..15 | indice dans une table de couples (fnum, block), écrits dans les registres de hauteur des voies 6 et 8 — c'est ce qui règle la grosse caisse et le tom |
| `noise_vol` | 0..15 | |

Une rafale dont la densité retombe est ce qui rend une explosion crédible.

## Catégories et tirage

Huit catégories, chacune un *a priori* : quelles couches sont actives, et
quelles plages pour chaque paramètre. Ce sont les événements d'un jeu, pas des
familles de synthèse — c'est ce qui rend le tirage utile.

**Tir · Explosion · Impact · Ramassage · Saut · Dégât · Menu · Alarme**, plus
un tirage libre sur tout l'espace.

`randomize(category, seed)` tire dans l'a priori.
`mutate(params, amount, locked)` perturbe chaque paramètre non verrouillé de
±`amount`, en restant dans les bornes.

Tirage et mutation sont **déterministes à graine donnée** : un son se retrouve.

## L'interface

Un onglet **Créer**, qui devient celui ouvert par défaut et qui **remplace**
l'onglet Paramétrique — il en est la version aboutie. L'onglet **Fichier
audio** reste à côté, inchangé.

```
┌─ CATEGORIES ────────────┐┌─ LE SON ──────────────────────┐
│ ▸ Tir      ▸ Explosion  ││  hauteur ╲___                 │
│ ▸ Impact   ▸ Ramassage  ││  volume  ███▄▄▁               │
│ ▸ Saut     ▸ Degat      ││  bruit    ┃  ┃ ┃              │
│ ▸ Menu     ▸ Alarme     ││  [ ▶ ECOUTER ]  espace        │
│  ┌───────────────────┐  │└───────────────────────────────┘
│  │   TIRER AU SORT   │  │┌─ VARIANTES ───────────────────┐
│  └───────────────────┘  ││  1▸ 2▸ 3▸ 4▸ 5▸ 6▸ 7▸ 8▸      │
│  [ MUTER  ▏▎▍▌▋ 30% ]   ││  clic = ecouter, re-clic = ok │
└─────────────────────────┘└───────────────────────────────┘
┌─ AFFINER (replie) ────────────────────────────────────────┐
│ 🔒 attaque ▏▎▍▌   chute ▍▌▋▊   hauteur ▎▍   glisse ▌▋ ... │
└───────────────────────────────────────────────────────────┘
  128/255 commandes · 386 o · [ GARDER DANS LA BANQUE ]
```

Ce qui fait la différence entre un jouet et un outil, et qui doit être là dès
la première version :

- **un cadenas par paramètre.** La mutation ne touche pas ce qui est verrouillé.
  C'est le seul moyen de converger : on fige ce qui est bon, on relance sur le
  reste.
- **un historique.** Chaque tirage et chaque mutation adoptée y entre ; on ne
  perd jamais un bon hasard.
- **la barre d'espace rejoue**, et tout changement de réglage rejoue.

## La banque

Les sons gardés forment une banque nommée. L'app en produit les **deux fichiers
cohérents entre eux** :

- `soundFX.asm` — la table `soundFX.soundTable` et les blocs de données ;
- `soundFX.const.asm` — les `equ` des identifiants, dans le même ordre.

Aujourd'hui ces deux fichiers se maintiennent à la main, et une divergence
entre l'ordre de la table et celui des constantes ne se voit pas au build : le
mauvais son se joue, sans erreur. La banque supprime cette classe de bug.

Budget affiché en permanence : commandes/255 par son, total en octets de la
banque.

### La voie reste choisie à la main

Le numéro de voie YM2413 est **un réglage par son**, conservé tel quel — il est
d'ailleurs déjà une donnée du format, le deuxième octet de l'en-tête du bloc.
L'outil ne peut pas deviner quelles voies la musique d'un jeu laisse libres :
c'est une information que seul l'auteur du jeu possède, et elle change d'un
projet à l'autre, voire d'un niveau à l'autre.

La banque porte donc une **voie par défaut**, réglée une fois, que chaque son
peut surcharger. C'est sans risque : quand un bruitage en interrompt un autre,
le driver coupe la voie du son *sortant* (`soundFX.currChan`), pas une voie
figée — deux sons sur deux voies différentes s'enchaînent correctement.

Deux validations à l'export, par son :

- couche bruit active → la voie doit être entre 0 et 5, faute de quoi le mode
  rythme efface la couche mélodique (voir Garde-fous) ;
- la voie est rappelée en commentaire dans l'en-tête de chaque bloc généré,
  pour qu'une relecture du `.asm` dise tout de suite sur quoi le son joue.

La banque se sérialise en JSON — les paramètres, pas les données rendues, pour
qu'un son reste modifiable — dans un fichier dont l'utilisateur choisit le
chemin, aux côtés des deux `.asm` exportés.

## Garde-fous

**La couche bruit n'est jamais activée par l'outil.** Ni par défaut, ni par une
catégorie, ni par une mutation : seul l'utilisateur la coche. Les catégories
décrivent en revanche le kit et la forme de rafale qui conviendraient, pour
qu'elle sonne juste le jour où il l'active. Le mode rythme réquisitionne les voies
6-8 de la puce. La musique de battlesquadron s'en sert déjà : un bruitage qui
écrit `$0E` écrasera l'état de batterie de la musique le temps d'une trame.
L'avertissement va dans l'interface **et** dans l'en-tête de l'ASM généré, comme
celui de l'instrument custom.

**Voies utilisables avec la couche bruit : 0 à 5.** Deux contraintes se
superposent, et ce n'est pas la plus évidente qui lie :

- *l'adressage* — le générateur pré-soustrait la voie des registres rythme ; à
  partir de la voie 7, `$16 − 7 = $0F` retombe dans la plage écrite verbatim et
  viserait le mauvais registre. Cette contrainte seule donnerait 6 ;
- *le matériel* — le mode rythme réquisitionne les voies 6, 7 et 8. Une couche
  mélodique posée sur l'une d'elles n'est pas dégradée, elle est **effacée**.

Mesure sur l'émulateur, note tenue, RMS sur 250 ms, avec et sans mode rythme :
voies 0 à 5 identiques (0,02584) ; voie 6 → 0,00000, voie 7 → 0,00011, voie 8 →
0,00000. C'est donc **5**, et un bruitage sur la voie 6 serait sorti
silencieusement amputé de tout son corps tonal. Le générateur refuse au-delà,
en le disant.

**Instrument custom hors périmètre pour cette version.** Il existe déjà côté
fichier audio, avec ses avertissements ; le mêler au tirage au sort
multiplierait les façons de casser la musique.

## Architecture

Fichiers nouveaux :

- `to8sfx/design.py` — `SfxParams`, les a priori par catégorie, `randomize`,
  `mutate`, et le rendu `params → (frames, masques de bruit par trame)` ;
- `to8sfx/rhythm.py` — la section rythme : jeux de percussions, écritures de
  registres, pré-soustraction de la voie et sa validation ;
- `to8sfx/bank.py` — la banque, sa sérialisation, la génération des deux
  fichiers ASM.

Fichiers modifiés :

- `to8sfx/codegen.py` — `frames_to_commands` accepte une piste de bruit
  (un masque `$0E` par trame, `None` quand la couche est éteinte) et le numéro
  de voie ; l'initialisation des registres rythme est émise une fois en tête ;
- `to8sfx/server.py` — endpoints du tirage, de la mutation, des variantes et de
  la banque ;
- `static/index.html` — l'onglet Créer ;
- `cli.py` — sous-commandes `create` et `bank`.

Intouchés : `analyze.py`, `melody.py`, `instruments.py`, `importer.py`,
`opll.py`, et l'onglet Fichier audio. `parametric.py` est absorbé par
`design.py` — ses huit presets deviennent les a priori des catégories.

## Tests

Ce qui doit être verrouillé, et pourquoi :

- **tirage déterministe** — même graine, mêmes paramètres ; sans quoi
  l'historique et la banque ne veulent rien dire ;
- **la mutation respecte les cadenas** — un paramètre verrouillé ne bouge
  jamais, et aucun paramètre ne sort de ses bornes ;
- **chaque catégorie tient dans le budget** — sur 200 tirages par catégorie,
  aucun ne ressort avec `truncated`. Vérifier « ne dépasse pas 255 commandes »
  ne prouverait rien : `fit_to_budget` tronque en dernier recours, donc c'est
  vrai par construction ;
- **les registres rythme atterrissent au bon endroit** — on simule l'addition
  faite par le driver sur le flux émis et on vérifie qu'on retombe exactement
  sur `$16/$26/$36`… ; et que la couche est refusée au-delà de la voie 6 ;
- **ton et bruit coexistent** — mesure sur l'émulateur : la note mélodique garde
  son niveau quand le mode rythme s'active ;
- **l'arpège produit bien N hauteurs distinctes**, et son coût reste sous
  90 commandes par seconde ;
- **aller-retour de la banque** — la banque génère les deux fichiers, on les
  relit avec `importer.parse_asm_sound`, les tailles et l'ordre concordent, et
  chaque `equ` de `soundFX.const.asm` pointe la bonne entrée de la table.

## Hors périmètre

Instrument custom dans le tirage ; import d'une banque existante depuis un
`soundFX.asm` du jeu ; refonte de l'onglet Fichier audio ; toute modification
du moteur.
