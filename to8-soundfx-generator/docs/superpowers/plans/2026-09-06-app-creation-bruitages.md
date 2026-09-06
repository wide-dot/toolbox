# App de création de bruitages — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de `to8-soundfx-generator` une app de création de bruitages dont la boucle centrale est le tirage au sort sur trois couches (ton, arpège, bruit), avec une banque qui écrit `soundFX.asm` et `soundFX.const.asm` cohérents entre eux.

**Architecture:** Un module `design.py` porte les paramètres, les *a priori* par catégorie, le tirage, la mutation et le rendu vers des trames. `rhythm.py` isole la section rythme du YM2413 et son adressage. `codegen.py` apprend à entrelacer une piste de bruit dans le flux de commandes existant. `bank.py` assemble les sons gardés et produit les deux fichiers assembleur. Le serveur et l'interface gagnent un onglet **Créer** ; l'onglet **Fichier audio** n'est pas touché.

**Tech Stack:** Python 3.10+, numpy, ffmpeg, emu2413 via ctypes. Serveur `http.server` de la bibliothèque standard. Aucune dépendance nouvelle.

**Spec:** `docs/superpowers/specs/2026-09-06-app-creation-bruitages-design.md`

## Global Constraints

- **Aucune dépendance nouvelle.** numpy et ffmpeg, rien d'autre. Le serveur reste sur la bibliothèque standard.
- **Tout le code, les commentaires et les messages sont en français**, sans accents dans les fichiers `.py` (le reste du dépôt suit cette règle). Le Markdown et le HTML, eux, sont accentués.
- **Commentaires : expliquer le pourquoi, pas le quoi.** Le dépôt documente les pièges matériels dans le code même ; suivre ce ton.
- **Budget dur : 255 commandes par bruitage**, compteur sur un octet. `codegen.MAX_COMMANDS`.
- **Voie YM2413 : réglage par son**, valeur par défaut au niveau de la banque. Avec la couche bruit, voies 0 à 5 seulement : le mode rythme réquisitionne les voies 6 à 8 et efface toute couche mélodique posée dessus (mesuré sur l'émulateur).
- **La couche bruit est désactivée par défaut** et porte son avertissement dans l'interface et dans l'en-tête de l'ASM généré.
- **Ne pas toucher** `analyze.py`, `melody.py`, `instruments.py`, `importer.py`, `opll.py`, ni l'onglet Fichier audio.
- **Tests** : fonctions `test_*` avec de simples `assert`, lancées par `python3 -m tests`. Chaque nouveau fichier de test est ajouté à la liste de `tests/__main__.py`.
- **Commits** : conventionnels, en français, sans trailer de session.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `to8sfx/rhythm.py` | *créé* — section rythme : jeux de percussions, écritures d'armement, adressage (pré-soustraction de la voie) et sa validation |
| `to8sfx/design.py` | *créé* — `SfxParams`, rendu vers trames + piste de bruit, *a priori* par catégorie, tirage, mutation |
| `to8sfx/bank.py` | *créé* — banque, sérialisation JSON, génération des deux fichiers assembleur |
| `to8sfx/codegen.py` | *modifié* — `frames_to_commands` accepte une piste de bruit et la voie |
| `to8sfx/server.py` | *modifié* — endpoints de création et de banque |
| `static/index.html` | *modifié* — onglet Créer, en remplacement de Paramétrique |
| `cli.py` | *modifié* — sous-commandes `create` et `bank`, retrait de `sweep` |
| `to8sfx/parametric.py` | *supprimé* — absorbé par `design.py` |
| `tests/test_rhythm.py`, `tests/test_design.py`, `tests/test_bank.py` | *créés* |

---

### Task 1 : la section rythme et son adressage

**Files:**
- Create: `to8sfx/rhythm.py`
- Create: `tests/test_rhythm.py`
- Modify: `tests/__main__.py:6`

**Interfaces:**
- Consumes: `opll.render`, `opll.freq_to_fnum_block`, `opll.REG_RHYTHM`
- Produces:
  - `rhythm.HITS: dict[str, int]` — masques de déclenchement par nom
  - `rhythm.KIT_ORDER: tuple[str, ...]`
  - `rhythm.RHYTHM_ON: int` = `0x20`
  - `rhythm.MAX_CHANNEL: int` = `5`
  - `rhythm.encode(reg: int, channel: int) -> int`
  - `rhythm.arm_writes(noise_pitch: int, noise_vol: int) -> list[tuple[int, int]]` — couples (registre **absolu**, valeur)
  - `rhythm.check_channel(channel: int) -> None` — lève `ValueError`

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_rhythm.py` :

```python
"""Section rythme du YM2413 : la seule source de bruit de la puce.

Le driver ecrit les registres <= $0F tels quels et ajoute le numero de voie aux
autres (engine/sound/soundFX.asm, etiquette @NotCustom). Les registres des voies
rythmiques sont au-dessus de $0F : il faut donc EMETTRE reg - voie pour que la
puce recoive reg. Ces tests verrouillent cet aller-retour, parce qu'une erreur
ici ne fait pas de bruit : elle ecrit dans un autre registre, en silence.
"""

import sys

import numpy as np

from to8sfx import opll, rhythm

RATE = 44100


def _driver_sees(emitted_reg, channel):
    """Ce que la puce recoit, en rejouant la regle du driver."""
    return emitted_reg if emitted_reg <= 0x0F else emitted_reg + channel


def test_encode_round_trips_through_the_driver_rule():
    for channel in range(0, rhythm.MAX_CHANNEL + 1):
        for reg, _val in rhythm.arm_writes(noise_pitch=4, noise_vol=4):
            emitted = rhythm.encode(reg, channel)
            assert _driver_sees(emitted, channel) == reg, (
                f"voie {channel} : emis ${emitted:02X} -> "
                f"${_driver_sees(emitted, channel):02X}, voulu ${reg:02X}")
    print(f"  aller-retour verifie sur les voies 0 a {rhythm.MAX_CHANNEL}")


def test_rhythm_control_register_is_never_shifted():
    """$0E est <= $0F : il doit passer verbatim depuis n'importe quelle voie."""
    for channel in range(0, 9):
        assert rhythm.encode(opll.REG_RHYTHM, channel) == opll.REG_RHYTHM
    print("  $0E passe verbatim depuis toutes les voies")


def test_channels_above_six_are_refused():
    """A partir de la voie 7, $16 - 7 = $0F retombe dans la plage ecrite
    verbatim et viserait le registre de controle du rythme."""
    for channel in (7, 8):
        try:
            rhythm.check_channel(channel)
        except ValueError:
            continue
        raise AssertionError(f"voie {channel} acceptee alors qu'elle est hors plage")
    for channel in range(0, 7):
        rhythm.check_channel(channel)  # ne doit pas lever
    print("  voies 6 a 8 refusees, 0 a 5 acceptees")


def test_each_percussion_is_actually_noisy():
    """La caisse claire et la charleston doivent produire du bruit, pas un son
    pur : c'est toute la raison d'etre de cette couche."""
    def flatness(mask):
        ev = [(0, r, v) for r, v in rhythm.arm_writes(4, 4)]
        ev.append((0, opll.REG_RHYTHM, rhythm.RHYTHM_ON))
        ev.append((int(0.02 * RATE), opll.REG_RHYTHM, rhythm.RHYTHM_ON | mask))
        ev.append((int(0.10 * RATE), opll.REG_RHYTHM, rhythm.RHYTHM_ON))
        y = opll.render(ev, int(0.5 * RATE), RATE)[int(0.02 * RATE):int(0.25 * RATE)]
        p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2 + 1e-20
        return float(np.exp(np.mean(np.log(p))) / np.mean(p))

    sd = flatness(rhythm.HITS["SD"])
    hh = flatness(rhythm.HITS["HH"])
    assert sd > 0.15, f"caisse claire pas assez bruitee : platitude {sd:.3f}"
    assert hh > 0.05, f"charleston pas assez bruitee : platitude {hh:.3f}"
    print(f"  platitude spectrale : caisse claire {sd:.3f}, charleston {hh:.3f}")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n  {e}")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

Run: `cd to8-soundfx-generator && python3 -m tests.test_rhythm`
Expected: `ModuleNotFoundError: No module named 'to8sfx.rhythm'`

- [ ] **Step 3 : écrire `to8sfx/rhythm.py`**

```python
"""Section rythme du YM2413 : la seule source de BRUIT de la puce.

La voie melodique ne sait produire que des sons periodiques ; c'est pourquoi
une explosion enregistree ne se convertit pas. Le registre $0E bascule la puce
en mode rythme : les voies 6, 7 et 8 deviennent cinq percussions, dont la
caisse claire et la charleston sont a base de bruit. Platitude spectrale
mesuree sur l'emulateur : 0,27 et 0,12, contre 0,00 pour une note melodique.

Adressage : le driver ecrit les registres <= $0F tels quels et AJOUTE le numero
de voie aux autres. Les registres des voies rythmiques etant au-dessus de $0F,
il faut emettre `reg - voie` pour que la puce recoive `reg`. A partir de la
voie 7, $16 - 7 = $0F retomberait dans la plage ecrite verbatim et viserait le
registre de controle du rythme : la couche est alors refusee.
"""

from __future__ import annotations

from .opll import REG_RHYTHM, freq_to_fnum_block

RHYTHM_ON = 0x20  # bit 5 de $0E : bascule en mode rythme

# Masques de declenchement, bits 0 a 4 de $0E.
HITS: dict[str, int] = {
    "BD": 0x10,   # grosse caisse (voie 6)
    "SD": 0x08,   # caisse claire (voie 7)
    "TOM": 0x04,  # tom          (voie 8)
    "CYM": 0x02,  # cymbale      (voie 8)
    "HH": 0x01,   # charleston   (voie 7)
}
KIT_ORDER: tuple[str, ...] = ("BD", "SD", "TOM", "CYM", "HH")

# Voie maximale utilisable avec la couche bruit : au-dela, la
# pre-soustraction retombe sous $0F. Voir l'en-tete du module.
MAX_CHANNEL = 6

# Hauteurs de la grosse caisse et du tom : 16 crans, du plus grave au plus
# aigu. Les percussions rythmiques prennent leur hauteur dans les registres
# de hauteur des voies 6 et 8 comme une note ordinaire.
_PITCH_HZ = [40.0 * (300.0 / 40.0) ** (i / 15.0) for i in range(16)]
PITCH_TABLE = [freq_to_fnum_block(f) for f in _PITCH_HZ]


def check_channel(channel: int) -> None:
    """Leve ValueError si la couche bruit ne peut pas viser juste sur cette voie."""
    if not 0 <= channel <= MAX_CHANNEL:
        raise ValueError(
            f"couche bruit impossible sur la voie {channel} : les registres de "
            f"la section rythme recoivent le numero de voie, et au-dela de la "
            f"voie {MAX_CHANNEL} la compensation retombe sous $0F. "
            f"Choisir une voie de 0 a {MAX_CHANNEL}, ou couper la couche bruit."
        )


def encode(reg: int, channel: int) -> int:
    """Registre a EMETTRE pour que la puce recoive `reg`."""
    if reg <= 0x0F:
        return reg
    check_channel(channel)
    return reg - channel


def arm_writes(noise_pitch: int, noise_vol: int) -> list[tuple[int, int]]:
    """Les ecritures qui arment la section rythme, en registres ABSOLUS.

    La documentation du YM2413 fixe le volume des percussions dans les quartets
    des registres $36-$38 ; la hauteur de la grosse caisse et du tom se regle
    comme celle d'une note.
    """
    pitch = max(0, min(15, int(noise_pitch)))
    vol = max(0, min(15, int(noise_vol)))
    fnum, block = PITCH_TABLE[pitch]
    lo = fnum & 0xFF
    hi = ((fnum >> 8) & 1) | ((block & 7) << 1)

    return [
        (0x16, lo), (0x26, hi), (0x36, (vol << 4) | vol),   # voie 6 : grosse caisse
        (0x17, 0x50), (0x27, 0x05), (0x37, (vol << 4) | vol),  # voie 7 : charleston + caisse claire
        (0x18, lo), (0x28, hi), (0x38, (vol << 4) | vol),   # voie 8 : tom + cymbale
    ]


def mask_of(names) -> int:
    """Masque de declenchement pour un ensemble de percussions."""
    m = 0
    for n in names:
        m |= HITS.get(n, 0)
    return m


__all__ = ["RHYTHM_ON", "HITS", "KIT_ORDER", "MAX_CHANNEL", "PITCH_TABLE",
           "REG_RHYTHM", "check_channel", "encode", "arm_writes", "mask_of"]
```

- [ ] **Step 4 : brancher le fichier de test dans la suite**

Dans `tests/__main__.py`, remplacer la ligne :

```python
for mod in ("tests.test_opll", "tests.test_analyze", "tests.test_melody"):
```

par :

```python
for mod in ("tests.test_opll", "tests.test_analyze", "tests.test_rhythm",
            "tests.test_melody"):
```

- [ ] **Step 5 : lancer les tests, les quatre doivent passer**

Run: `python3 -m tests.test_rhythm && python3 -m tests`
Expected: 4 nouveaux `OK`, et les 19 anciens toujours `OK`.

- [ ] **Step 6 : commit**

```bash
git add to8sfx/rhythm.py tests/test_rhythm.py tests/__main__.py
git commit -m "feat(rythme): section percussion du YM2413 et adressage des registres"
```

---

### Task 2 : entrelacer une piste de bruit dans le flux de commandes

**Files:**
- Modify: `to8sfx/codegen.py:73-121` (`frames_to_commands`), `to8sfx/codegen.py:124-158` (`fit_to_budget`)
- Create: `tests/test_codegen_noise.py`
- Modify: `tests/__main__.py:6`

**Interfaces:**
- Consumes: `rhythm.RHYTHM_ON`, `rhythm.encode`, `rhythm.arm_writes`, `rhythm.check_channel`, `opll.REG_RHYTHM`
- Produces:
  - `codegen.frames_to_commands(frames, custom_patch=None, noise=None, channel=0, noise_pitch=4, noise_vol=4) -> list[Command]`
  - `codegen.fit_to_budget(frames, max_commands=255, custom_patch=None, quantize_pitch=True, noise=None, channel=0, noise_pitch=4, noise_vol=4) -> (list[Command], list[Frame], dict)`
  - `noise` : `list[int] | None`, un masque de declenchement (sans le bit `RHYTHM_ON`) par trame, ou `None` quand la couche est eteinte.

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_codegen_noise.py` :

```python
"""Entrelacement de la couche bruit dans le flux de commandes.

Une seule voie melodique et la section rythme partagent le meme flux : c'est ce
qui permet a un bruitage d'avoir un corps tonal ET des frappes de bruit. Deux
choses doivent tenir : la note ne doit pas etre abimee par la presence du
rythme, et les ecritures rythmiques doivent atterrir sur les bons registres
apres l'addition faite par le driver.
"""

import sys

import numpy as np

from to8sfx import codegen, opll, rhythm

RATE = 44100
CHANNEL = 4


def _tone_frames(n=25, midi=69):
    fnum, block = opll.freq_to_fnum_block(opll.midi_to_freq(midi))
    return [opll.Frame(True, fnum, block, 0, 12) for _ in range(n)]


def test_noise_registers_land_on_the_chip_registers():
    """Apres l'addition du driver, on doit retomber exactement sur $16..$38."""
    noise = [0] * 10
    noise[3] = rhythm.HITS["BD"]
    cmds = codegen.frames_to_commands(_tone_frames(10), noise=noise, channel=CHANNEL)
    seen = {c.reg + CHANNEL if c.reg > 0x0F else c.reg for c in cmds}
    for reg, _ in rhythm.arm_writes(4, 4):
        assert reg in seen, f"registre ${reg:02X} jamais atteint"
    assert opll.REG_RHYTHM in seen, "$0E jamais ecrit"
    print(f"  {len(seen)} registres atteints, armement complet")


def test_hit_is_a_rising_edge():
    """Une frappe est un front montant : le bit doit retomber ensuite, sinon la
    percussion ne se redeclenche jamais."""
    noise = [0, 0, rhythm.HITS["SD"], 0, rhythm.HITS["SD"], 0]
    cmds = codegen.frames_to_commands(_tone_frames(6), noise=noise, channel=CHANNEL)
    vals = [c.data for c in cmds if c.reg == opll.REG_RHYTHM]
    on = rhythm.RHYTHM_ON | rhythm.HITS["SD"]
    assert vals.count(on) == 2, f"deux frappes attendues, ecritures $0E : {vals}"
    assert rhythm.RHYTHM_ON in vals, "le bit de declenchement ne retombe jamais"
    print(f"  {vals.count(on)} fronts montants, relachement present")


def test_tone_survives_the_noise_layer():
    """La note melodique doit garder son niveau quand le rythme s'active."""
    def rms(cmds):
        ev, n = codegen.commands_to_events(cmds, CHANNEL)
        y = opll.render(ev, n)
        a, b = int(0.10 * RATE), int(0.25 * RATE)
        return float(np.sqrt(np.mean(y[a:b] ** 2)))

    plain = rms(codegen.frames_to_commands(_tone_frames(40)))
    noise = [0] * 40
    noise[30] = rhythm.HITS["BD"]
    mixed = rms(codegen.frames_to_commands(_tone_frames(40), noise=noise, channel=CHANNEL))
    assert mixed > plain * 0.8, f"la note est ecrasee : {plain:.4f} -> {mixed:.4f}"
    print(f"  note seule {plain:.4f}, avec rythme {mixed:.4f}")


def test_noise_layer_refuses_channel_seven():
    noise = [0, rhythm.HITS["BD"]]
    try:
        codegen.frames_to_commands(_tone_frames(2), noise=noise, channel=7)
    except ValueError:
        print("  voie 7 refusee avec la couche bruit")
        return
    raise AssertionError("voie 7 acceptee alors que l'adressage y est faux")


def test_no_noise_means_no_extra_command():
    """noise=None doit laisser le flux rigoureusement identique a l'existant."""
    a = codegen.frames_to_commands(_tone_frames(20))
    b = codegen.frames_to_commands(_tone_frames(20), noise=None, channel=CHANNEL)
    assert [(c.reg, c.data, c.delay) for c in a] == [(c.reg, c.data, c.delay) for c in b]
    print(f"  {len(a)} commandes, identiques sans couche bruit")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n  {e}")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

Run: `python3 -m tests.test_codegen_noise`
Expected: `TypeError: frames_to_commands() got an unexpected keyword argument 'noise'`

- [ ] **Step 3 : modifier `frames_to_commands`**

Dans `to8sfx/codegen.py`, ajouter l'import en tête (après l'import de `.opll`) :

```python
from . import rhythm
```

Remplacer la signature et le corps de `frames_to_commands` par :

```python
def frames_to_commands(frames: list[Frame], custom_patch: bytes | None = None,
                       noise: list[int] | None = None, channel: int = 0,
                       noise_pitch: int = 4, noise_vol: int = 4) -> list[Command]:
    """Trames -> flux de commandes du driver.

    `noise` porte, pour chaque trame, le masque de declenchement des percussions
    (sans le bit RHYTHM_ON, qui est ajoute ici). None quand la couche est
    eteinte : le flux est alors rigoureusement celui d'avant.

    Les registres de la section rythme recoivent le numero de voie de la part du
    driver ; `rhythm.encode` les pre-soustrait. `commands_to_events`, qui sert au
    preview, rejoue exactement la meme regle, donc ce qu'on entend est ce que la
    puce recevra.
    """
    cmds: list[Command] = []
    shadow: dict[int, int | None] = {REG_FNUM_LO: None, REG_BLOCK: None, REG_INST_VOL: None}

    if custom_patch is not None:
        # La commande $FF ecrit les 8 registres du patch PUIS selectionne
        # l'instrument 0 au volume 0 sur la voie. Son delai est implicitement 0.
        cmds.append(Command(CMD_CUSTOM_PATCH, 0, 0, patch=bytes(custom_patch)))
        shadow[REG_INST_VOL] = 0x00

    noise_shadow: int | None = None
    if noise is not None:
        rhythm.check_channel(channel)
        # Armer la section rythme une fois pour toutes, avant la premiere trame.
        for reg, val in rhythm.arm_writes(noise_pitch, noise_vol):
            cmds.append(Command(rhythm.encode(reg, channel), val, 0))
        cmds.append(Command(rhythm.encode(opll.REG_RHYTHM, channel),
                            rhythm.RHYTHM_ON, 0))
        noise_shadow = rhythm.RHYTHM_ON

    for i, f in enumerate(frames):
        if f.voiced:
            # Debut de note en mode melodique : le key-on doit repasser par 0
            # pour que l'enveloppe soit relancee (elle est declenchee sur front,
            # pas sur niveau). Sans ca les notes s'enchainent en legato.
            if f.attack and shadow[REG_BLOCK] is not None and (shadow[REG_BLOCK] & KEY_ON):
                off = shadow[REG_BLOCK] & ~KEY_ON
                cmds.append(Command(REG_BLOCK, off, 0))
                shadow[REG_BLOCK] = off
            want = {
                REG_INST_VOL: (f.instrument << 4) | (f.volume & 0x0F),
                REG_FNUM_LO: f.fnum & 0xFF,
                REG_BLOCK: ((f.fnum >> 8) & 1) | ((f.block & 7) << 1) | KEY_ON,
            }
        else:
            # Couper la note ne demande que d'effacer le key-on : on laisse
            # hauteur et volume tels quels, ca economise deux commandes.
            prev = shadow[REG_BLOCK] or 0
            want = {REG_BLOCK: prev & ~KEY_ON}

        # ordre volontaire : instrument/volume, puis F-Num bas, puis block+key-on.
        # Le key-on est ecrit en dernier pour que la hauteur soit complete au
        # moment ou la note demarre.
        changed = [(r, want[r]) for r in (REG_INST_VOL, REG_FNUM_LO, REG_BLOCK)
                   if r in want and shadow[r] != want[r]]

        if noise is not None:
            wanted_noise = rhythm.RHYTHM_ON | (noise[i] if i < len(noise) else 0)
            if wanted_noise != noise_shadow:
                changed.append((rhythm.encode(opll.REG_RHYTHM, channel), wanted_noise))
                noise_shadow = wanted_noise

        if changed:
            for reg, val in changed:
                cmds.append(Command(reg, val, 0))
                if reg in shadow:
                    shadow[reg] = val
            cmds[-1].delay = 1
        elif cmds:
            if cmds[-1].delay < MAX_DELAY:
                cmds[-1].delay += 1
            else:
                # delai sature : on reecrit un registre a l'identique, c'est
                # inoffensif et ca repart pour 255 ticks
                cmds.append(Command(REG_FNUM_LO, shadow[REG_FNUM_LO] or 0, 1))
    return cmds
```

Ajouter `from . import opll` en tête si `opll` n'est pas déjà importé comme module (le fichier importe aujourd'hui des noms précis depuis `.opll` ; ajouter `from . import opll` à côté).

- [ ] **Step 4 : faire suivre `fit_to_budget`**

Remplacer la signature et les deux appels à `frames_to_commands` dans `fit_to_budget` :

```python
def fit_to_budget(
    frames: list[Frame],
    max_commands: int = MAX_COMMANDS,
    custom_patch: bytes | None = None,
    quantize_pitch: bool = True,
    noise: list[int] | None = None,
    channel: int = 0,
    noise_pitch: int = 4,
    noise_vol: int = 4,
):
```

et à l'intérieur, les deux appels deviennent :

```python
        cmds = frames_to_commands(simple, custom_patch, noise, channel,
                                  noise_pitch, noise_vol)
```

(le second, celui du dernier recours, garde son `[:max_commands]`).

- [ ] **Step 5 : brancher le fichier de test**

Dans `tests/__main__.py`, la liste devient :

```python
for mod in ("tests.test_opll", "tests.test_analyze", "tests.test_rhythm",
            "tests.test_codegen_noise", "tests.test_melody"):
```

- [ ] **Step 6 : lancer toute la suite**

Run: `python3 -m tests`
Expected: les 23 anciens et nouveaux `OK`, aucun `FAIL`. Le test `test_no_noise_means_no_extra_command` prouve que rien n'a bougé pour l'onglet Fichier audio.

- [ ] **Step 7 : commit**

```bash
git add to8sfx/codegen.py tests/test_codegen_noise.py tests/__main__.py
git commit -m "feat(codegen): entrelacer une piste de bruit dans le flux de commandes"
```

---

### Task 3 : les paramètres et leur rendu

**Files:**
- Create: `to8sfx/design.py`
- Create: `tests/test_design.py`
- Modify: `tests/__main__.py:6`

**Interfaces:**
- Consumes: `opll.Frame`, `opll.freq_to_fnum_block`, `opll.midi_to_freq`, `opll.freq_to_midi`, `rhythm.HITS`, `rhythm.KIT_ORDER`, `analyze.FRAME_RATE`
- Produces:
  - `design.SfxParams` (dataclass, tous les champs de la spec, `to_dict()` / `from_dict()`)
  - `design.SfxParams.duration_frames -> int` (propriété)
  - `design.render(p: SfxParams) -> tuple[list[Frame], list[int] | None]`
  - `design.BOUNDS: dict[str, tuple[float, float]]` — bornes par paramètre numérique

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_design.py` :

```python
"""Le modele de son : enveloppe, hauteur, arpege, bruit."""

import sys

from to8sfx import design, opll, rhythm


def _midis(frames):
    return [round(opll.freq_to_midi(opll.fnum_block_to_freq(f.fnum, f.block)))
            for f in frames if f.voiced]


def test_duration_is_the_envelope():
    """La duree n'est pas un reglage : elle vaut attaque + tenue + chute. En
    faire un parametre independant permettrait de la mettre en contradiction
    avec l'enveloppe qui la compose."""
    p = design.SfxParams(attack_frames=2, hold_frames=3, decay_frames=10)
    assert p.duration_frames == 15
    frames, _ = design.render(p)
    assert len(frames) == 15, f"{len(frames)} trames pour une duree de 15"
    print("  duree = attaque + tenue + chute")


def test_envelope_rises_then_falls():
    p = design.SfxParams(attack_frames=4, hold_frames=2, decay_frames=8,
                         vol_peak=0, vol_end=15)
    frames, _ = design.render(p)
    vols = [f.volume for f in frames]          # 0 = fort, 15 = faible
    assert vols[0] > vols[3], f"pas d'attaque : {vols[:5]}"
    assert vols[4] == 0 and vols[5] == 0, f"pas de palier : {vols}"
    assert vols[-1] >= 14, f"pas de chute : {vols[-3:]}"
    print(f"  enveloppe : {vols}")


def test_slide_delta_bends_the_glide():
    """L'inflexion est ce qui donne le glissement qui ralentit. Sans elle, une
    droite ; avec, une courbe."""
    straight, _ = design.render(design.SfxParams(
        attack_frames=0, hold_frames=0, decay_frames=20,
        f_start=1200, slide=-0.5, slide_delta=0.0))
    bent, _ = design.render(design.SfxParams(
        attack_frames=0, hold_frames=0, decay_frames=20,
        f_start=1200, slide=-0.5, slide_delta=0.04))
    a, b = _midis(straight), _midis(bent)
    assert a[-1] < b[-1], f"l'inflexion ne redresse rien : {a[-1]} vs {b[-1]}"
    mid = len(a) // 2
    assert abs(a[mid] - b[mid]) < abs(a[-1] - b[-1]), "l'ecart devrait croitre"
    print(f"  droit {a[0]}->{a[-1]}, inflechi {b[0]}->{b[-1]}")


def test_arpeggio_visits_every_step():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=12,
                         f_start=440, slide=0.0, arp_steps=(0, 4, 7),
                         arp_frames=1)
    frames, _ = design.render(p)
    got = sorted(set(_midis(frames)))
    assert len(got) == 3, f"{len(got)} hauteurs au lieu de 3 : {got}"
    assert got[1] - got[0] == 4 and got[2] - got[0] == 7, got
    print(f"  arpege : {[opll.midi_name(m) for m in got]}")


def test_arpeggio_off_when_arp_frames_is_zero():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=12,
                         f_start=440, slide=0.0, arp_steps=(0, 4, 7),
                         arp_frames=0)
    frames, _ = design.render(p)
    assert len(set(_midis(frames))) == 1, "l'arpege joue alors qu'il est eteint"
    print("  arp_frames=0 eteint bien l'arpege")


def test_noise_track_is_none_when_layer_is_off():
    """La couche bruit est desactivee par defaut : le mode rythme requisitionne
    les voies 6-8 et la musique du jeu peut s'en servir."""
    frames, noise = design.render(design.SfxParams())
    assert noise is None, "la couche bruit est active par defaut"
    print("  couche bruit eteinte par defaut")


def test_noise_burst_density_falls():
    """Une rafale dont la densite retombe : c'est ce qui fait une explosion."""
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=40,
                         noise_on=True, noise_kit=("BD", "SD"), noise_hits=16,
                         noise_spread_frames=40, noise_accel=-0.8)
    _, noise = design.render(p)
    assert noise is not None and len(noise) == 40
    first = sum(1 for v in noise[:20] if v)
    last = sum(1 for v in noise[20:] if v)
    assert first > last, f"la densite ne retombe pas : {first} puis {last}"
    assert all(v & ~0x1F == 0 for v in noise), "un masque deborde des bits 0-4"
    print(f"  rafale : {first} frappes puis {last}")


def test_repeat_restarts_the_pattern():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=20,
                         f_start=880, slide=-0.4, repeat_frames=5)
    frames, _ = design.render(p)
    m = _midis(frames)
    assert m[0] == m[5] == m[10], f"la repetition ne relance rien : {m}"
    assert any(f.attack for f in frames[5:6]), "pas de re-attaque a la relance"
    print(f"  repetition tous les 5 : {m[:12]}")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n  {e}")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

Run: `python3 -m tests.test_design`
Expected: `ModuleNotFoundError: No module named 'to8sfx.design'`

- [ ] **Step 3 : écrire la première moitié de `to8sfx/design.py`**

```python
"""Le modele de son de l'app de creation : parametres, et leur rendu.

Trois couches entrelacees dans un seul flux de commandes :

- TON, la voie melodique : enveloppe, hauteur, glissement et son inflexion,
  vibrato, jitter ;
- ARPEGE, la note qui saute entre plusieurs demi-tons a chaque trame ou
  presque. C'est le geste le plus caracteristique du son de puce, et il ne
  coute presque rien : 84 commandes pour une seconde a une marche par trame,
  43 a une marche sur deux, parce que le registre $20 change rarement ;
- BRUIT, la section rythme, seule source de bruit de la puce.

La duree n'est PAS un parametre : elle vaut attaque + tenue + chute. En faire
un reglage independant permettrait de la mettre en contradiction avec
l'enveloppe qui la compose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np

from . import rhythm
from .analyze import FRAME_RATE
from .opll import Frame, freq_to_fnum_block, freq_to_midi, midi_to_freq

MAX_FRAMES = 127  # 2,5 s : au-dela le budget de 255 commandes ne suit plus


@dataclass
class SfxParams:
    # --- enveloppe de volume, en trames de 20 ms ---
    attack_frames: int = 1
    hold_frames: int = 2
    decay_frames: int = 12
    vol_peak: int = 0    # 0 = fort
    vol_end: int = 15    # 15 = silence

    # --- hauteur ---
    f_start: float = 900.0
    slide: float = -0.6        # demi-tons par trame
    slide_delta: float = 0.0   # demi-ton par trame au carre : l'inflexion
    pitch_curve: str = "exp"

    # --- modulations ---
    vibrato_hz: float = 0.0
    vibrato_cents: float = 0.0
    jitter_cents: float = 0.0

    # --- arpege ---
    arp_steps: tuple[int, ...] = ()
    arp_frames: int = 0        # 0 = arpege eteint
    arp_retrigger: bool = False

    # --- timbre ---
    instrument: int = 15

    # --- repetition ---
    repeat_frames: int = 0     # 0 = pas de repetition

    # --- couche bruit (section rythme) ---
    noise_on: bool = False     # eteinte par defaut : voir l'avertissement
    noise_kit: tuple[str, ...] = ("BD",)
    noise_hits: int = 8
    noise_spread_frames: int = 12
    noise_accel: float = -0.5
    noise_pitch: int = 4
    noise_vol: int = 4

    seed: int = 0

    @property
    def duration_frames(self) -> int:
        n = self.attack_frames + self.hold_frames + self.decay_frames
        return max(1, min(MAX_FRAMES, int(n)))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["arp_steps"] = list(self.arp_steps)
        d["noise_kit"] = list(self.noise_kit)
        return d

    @staticmethod
    def from_dict(d: dict) -> "SfxParams":
        known = {f.name for f in fields(SfxParams)}
        out = {k: v for k, v in (d or {}).items() if k in known}
        if "arp_steps" in out:
            out["arp_steps"] = tuple(int(v) for v in out["arp_steps"])
        if "noise_kit" in out:
            out["noise_kit"] = tuple(str(v) for v in out["noise_kit"])
        return SfxParams(**out)


# Bornes des parametres numeriques. Le tirage et la mutation s'y tiennent, et
# l'interface s'en sert pour dimensionner ses curseurs : une seule source.
BOUNDS: dict[str, tuple[float, float]] = {
    "attack_frames": (0, 15),
    "hold_frames": (0, 40),
    "decay_frames": (1, 90),
    "vol_peak": (0, 15),
    "vol_end": (0, 15),
    "f_start": (40.0, 5000.0),
    "slide": (-3.0, 3.0),
    "slide_delta": (-0.2, 0.2),
    "vibrato_hz": (0.0, 25.0),
    "vibrato_cents": (0.0, 1200.0),
    "jitter_cents": (0.0, 1200.0),
    "arp_frames": (0, 8),
    "instrument": (1, 15),
    "repeat_frames": (0, 60),
    "noise_hits": (0, 40),
    "noise_spread_frames": (1, 90),
    "noise_accel": (-1.0, 1.0),
    "noise_pitch": (0, 15),
    "noise_vol": (0, 15),
}
INT_PARAMS = {"attack_frames", "hold_frames", "decay_frames", "vol_peak",
              "vol_end", "arp_frames", "instrument", "repeat_frames",
              "noise_hits", "noise_spread_frames", "noise_pitch", "noise_vol"}


def _envelope(p: SfxParams, n: int) -> np.ndarray:
    """Volume par trame, 0 = fort. Attaque depuis le silence, palier, chute."""
    vol = np.full(n, float(p.vol_end))
    i = 0
    if p.attack_frames > 0:
        k = min(p.attack_frames, n)
        vol[:k] = np.linspace(15.0, float(p.vol_peak), k, endpoint=False)
        i = k
    if p.hold_frames > 0 and i < n:
        k = min(p.hold_frames, n - i)
        vol[i:i + k] = float(p.vol_peak)
        i += k
    if i < n:
        vol[i:] = np.linspace(float(p.vol_peak), float(p.vol_end), n - i)
    return np.clip(np.round(vol), 0, 15).astype(int)


def render(p: SfxParams) -> tuple[list[Frame], list[int] | None]:
    """Parametres -> trames du driver, et piste de bruit (None si eteinte)."""
    n = p.duration_frames
    rng = np.random.default_rng(p.seed)

    # Indice local : la repetition relance le motif entier.
    if p.repeat_frames and p.repeat_frames > 0:
        local = np.arange(n) % p.repeat_frames
    else:
        local = np.arange(n)

    # Hauteur en demi-tons : depart + glissement + inflexion. L'inflexion est
    # la derivee seconde ; c'est elle qui donne le glissement qui ralentit.
    midi0 = freq_to_midi(max(p.f_start, 1.0))
    t = local.astype(float)
    midi = midi0 + p.slide * t + 0.5 * p.slide_delta * t * t

    # L'arpege s'ajoute en relatif : il se compose avec le glissement.
    attack_flags = np.zeros(n, dtype=bool)
    attack_flags[0] = True
    if p.arp_frames > 0 and p.arp_steps:
        step_idx = (local // p.arp_frames) % len(p.arp_steps)
        midi = midi + np.array([p.arp_steps[k] for k in step_idx], dtype=float)
        if p.arp_retrigger:
            changed = np.ones(n, dtype=bool)
            changed[1:] = step_idx[1:] != step_idx[:-1]
            attack_flags |= changed
    if p.repeat_frames and p.repeat_frames > 0:
        attack_flags |= (local == 0)

    freq = np.array([midi_to_freq(float(m)) for m in midi])

    if p.vibrato_hz > 0 and p.vibrato_cents > 0:
        phase = 2 * np.pi * p.vibrato_hz * (np.arange(n) / FRAME_RATE)
        freq = freq * 2.0 ** (p.vibrato_cents / 1200.0 * np.sin(phase))
    if p.jitter_cents > 0:
        freq = freq * 2.0 ** (rng.normal(0.0, p.jitter_cents / 1200.0, n))

    vol = _envelope(p, n)

    frames: list[Frame] = []
    for i in range(n):
        f = float(np.clip(freq[i], 20.0, 8000.0))
        fnum, block = freq_to_fnum_block(f)
        frames.append(Frame(True, fnum, block, int(vol[i]),
                            int(p.instrument), bool(attack_flags[i])))

    return frames, _noise_track(p, n, rng)


def _noise_track(p: SfxParams, n: int, rng) -> list[int] | None:
    """Rafale de frappes, dont la densite s'accelere ou retombe.

    Les instants sont tires sur une courbe de puissance u**gamma. Un exposant
    SUPERIEUR a 1 tasse les frappes au debut, donc la densite retombe : c'est
    une explosion. Un exposant inferieur a 1 les tasse a la fin, la densite
    accelere. D'ou le signe moins : noise_accel negatif doit donner gamma > 1.
    """
    if not p.noise_on or p.noise_hits <= 0 or not p.noise_kit:
        return None

    spread = max(1, min(int(p.noise_spread_frames), n))
    gamma = 2.0 ** (-float(p.noise_accel) * 2.0)
    track = [0] * n
    kit = [k for k in p.noise_kit if k in rhythm.HITS] or ["BD"]
    for k in range(int(p.noise_hits)):
        u = (k + 1) / float(p.noise_hits)
        pos = int(round((u ** gamma) * (spread - 1)))
        pos = max(0, min(n - 1, pos))
        track[pos] |= rhythm.HITS[kit[k % len(kit)]]
    return track
```

- [ ] **Step 4 : brancher le fichier de test et lancer**

Dans `tests/__main__.py`, insérer `"tests.test_design"` après `"tests.test_codegen_noise"`.

Run: `python3 -m tests.test_design`
Expected: les 8 tests `OK`.

- [ ] **Step 5 : lancer toute la suite**

Run: `python3 -m tests`
Expected: aucun `FAIL`.

- [ ] **Step 6 : commit**

```bash
git add to8sfx/design.py tests/test_design.py tests/__main__.py
git commit -m "feat(design): modele de son a trois couches et son rendu"
```

---

### Task 4 : catégories, tirage au sort, mutation et cadenas

**Files:**
- Modify: `to8sfx/design.py` (ajout en fin de fichier)
- Modify: `tests/test_design.py` (ajout de tests)

**Interfaces:**
- Consumes: `design.SfxParams`, `design.BOUNDS`, `design.INT_PARAMS`, `design.render`, `codegen.fit_to_budget`
- Produces:
  - `design.CATEGORIES: dict[str, dict]` — pour chaque catégorie, `{"label": str, "ranges": dict[str, tuple], "fixed": dict}`
  - `design.randomize(category: str, seed: int) -> SfxParams`
  - `design.mutate(p: SfxParams, amount: float, locked: set[str], seed: int) -> SfxParams`

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `tests/test_design.py`, avant le bloc `if __name__`:

```python
def test_randomize_is_deterministic():
    """Meme graine, memes parametres : sans quoi l'historique et la banque ne
    veulent rien dire."""
    for cat in design.CATEGORIES:
        a = design.randomize(cat, seed=1234)
        b = design.randomize(cat, seed=1234)
        assert a.to_dict() == b.to_dict(), f"{cat} n'est pas deterministe"
    c = design.randomize("tir", seed=1)
    d = design.randomize("tir", seed=2)
    assert c.to_dict() != d.to_dict(), "deux graines donnent le meme son"
    print(f"  {len(design.CATEGORIES)} categories, tirage deterministe")


def test_mutate_respects_locks_and_bounds():
    base = design.randomize("explosion", seed=7)
    locked = {"instrument", "f_start", "decay_frames"}
    m = design.mutate(base, amount=0.8, locked=locked, seed=3)
    for k in locked:
        assert getattr(m, k) == getattr(base, k), f"{k} a bouge malgre son cadenas"
    for k, (lo, hi) in design.BOUNDS.items():
        v = getattr(m, k)
        assert lo <= v <= hi, f"{k} = {v} hors de [{lo}, {hi}]"
    assert m.to_dict() != base.to_dict(), "la mutation n'a rien change"
    print(f"  {len(locked)} cadenas tenus, toutes les bornes respectees")


def test_every_category_fits_the_budget():
    """Sur 200 tirages par categorie, aucun ne doit ressortir tronque.

    Verifier qu'aucun ne depasse 255 commandes ne prouverait rien :
    fit_to_budget tronque en dernier recours, donc c'est vrai par construction.
    """
    from to8sfx import codegen

    worst = {}
    for cat in design.CATEGORIES:
        truncated = 0
        peak = 0
        for seed in range(200):
            p = design.randomize(cat, seed=seed)
            frames, noise = design.render(p)
            cmds, _, info = codegen.fit_to_budget(
                frames, noise=noise, channel=4,
                noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
            peak = max(peak, len(cmds))
            truncated += bool(info["truncated"])
        worst[cat] = (truncated, peak)
        assert truncated == 0, f"{cat} : {truncated}/200 tirages tronques"
    print("  " + ", ".join(f"{c} max {p} cmd" for c, (_, p) in worst.items()))
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

Run: `python3 -m tests.test_design`
Expected: `AttributeError: module 'to8sfx.design' has no attribute 'CATEGORIES'`

- [ ] **Step 3 : ajouter les catégories et le tirage à `to8sfx/design.py`**

Ajouter en fin de fichier :

```python
# --- Categories -------------------------------------------------------------
#
# Une categorie est un a priori sur l'espace des parametres : quelles couches
# sont actives, et dans quelles plages tirer. Ce sont des EVENEMENTS DE JEU, pas
# des familles de synthese — c'est ce qui rend le tirage utile : on cherche
# "une explosion", pas "un balayage descendant avec du jitter".
#
# `ranges` remplace la borne globale de BOUNDS pendant le tirage ; `fixed` force
# une valeur. Ce qui n'est cite ni dans l'un ni dans l'autre garde le defaut.

CATEGORIES: dict[str, dict] = {
    "tir": {
        "label": "Tir",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (3, 10), "f_start": (1200, 4000),
                   "slide": (-2.5, -0.8), "slide_delta": (0.0, 0.06),
                   "instrument": (12, 15), "jitter_cents": (0, 60)},
        "fixed": {"vol_peak": 1, "vol_end": 14, "noise_on": False},
    },
    "explosion": {
        "label": "Explosion",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 3),
                   "decay_frames": (15, 45), "f_start": (200, 700),
                   "slide": (-0.6, -0.1), "jitter_cents": (250, 900),
                   "instrument": (13, 14), "noise_hits": (10, 30),
                   "noise_spread_frames": (12, 45), "noise_accel": (-1.0, -0.4),
                   "noise_pitch": (0, 5), "noise_vol": (0, 5)},
        "fixed": {"vol_peak": 0, "vol_end": 15, "noise_on": True,
                  "noise_kit": ("BD", "SD", "TOM")},
    },
    "impact": {
        "label": "Impact",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 1),
                   "decay_frames": (4, 14), "f_start": (120, 500),
                   "slide": (-1.5, -0.3), "jitter_cents": (100, 400),
                   "instrument": (13, 14), "noise_hits": (1, 4),
                   "noise_spread_frames": (1, 4), "noise_pitch": (0, 6),
                   "noise_vol": (0, 4)},
        "fixed": {"vol_peak": 0, "vol_end": 15, "noise_on": True,
                  "noise_kit": ("BD", "TOM")},
    },
    "ramassage": {
        "label": "Ramassage",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (1, 4),
                   "decay_frames": (4, 12), "f_start": (500, 1400),
                   "slide": (0.0, 0.8), "arp_frames": (1, 3),
                   "instrument": (10, 12)},
        "fixed": {"vol_peak": 2, "vol_end": 12, "noise_on": False,
                  "arp_steps": (0, 4, 7, 12), "arp_retrigger": True},
    },
    "saut": {
        "label": "Saut",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (5, 14), "f_start": (200, 600),
                   "slide": (0.6, 2.2), "slide_delta": (-0.08, 0.0),
                   "instrument": (10, 15)},
        "fixed": {"vol_peak": 2, "vol_end": 13, "noise_on": False},
    },
    "degat": {
        "label": "Degat",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (15, 40), "f_start": (90, 300),
                   "slide": (-0.8, -0.2), "jitter_cents": (60, 250),
                   "instrument": (13, 14)},
        "fixed": {"vol_peak": 1, "vol_end": 15, "noise_on": False},
    },
    "menu": {
        "label": "Menu",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (1, 3),
                   "decay_frames": (2, 6), "f_start": (700, 2200),
                   "slide": (-0.3, 0.3), "instrument": (10, 12)},
        "fixed": {"vol_peak": 3, "vol_end": 12, "noise_on": False},
    },
    "alarme": {
        "label": "Alarme",
        "ranges": {"attack_frames": (0, 2), "hold_frames": (10, 30),
                   "decay_frames": (2, 8), "f_start": (400, 1100),
                   "slide": (-0.05, 0.05), "vibrato_hz": (4, 12),
                   "vibrato_cents": (300, 900), "repeat_frames": (0, 20),
                   "instrument": (5, 8)},
        "fixed": {"vol_peak": 2, "vol_end": 4, "noise_on": False},
    },
}


def _draw(rng, key, lo, hi):
    if key in INT_PARAMS:
        return int(rng.integers(int(lo), int(hi) + 1))
    return float(rng.uniform(lo, hi))


def _clamp(key, value):
    lo, hi = BOUNDS[key]
    v = max(lo, min(hi, value))
    return int(round(v)) if key in INT_PARAMS else float(v)


def randomize(category: str, seed: int) -> SfxParams:
    """Tire un son dans l'a priori d'une categorie. Deterministe a graine donnee."""
    cat = CATEGORIES.get(category)
    if cat is None:
        cat = {"ranges": {}, "fixed": {}}
    rng = np.random.default_rng(seed)

    p = SfxParams(seed=int(seed))
    ranges = cat.get("ranges", {})
    for key in BOUNDS:
        lo, hi = ranges.get(key, BOUNDS[key])
        setattr(p, key, _clamp(key, _draw(rng, key, lo, hi)))
    for key, value in cat.get("fixed", {}).items():
        setattr(p, key, value)
    return p


def mutate(p: SfxParams, amount: float, locked, seed: int) -> SfxParams:
    """Perturbe chaque parametre non verrouille, en restant dans ses bornes.

    Le cadenas est ce qui permet de converger : on fige ce qui est bon et on
    relance le hasard sur le reste. Sans lui, chaque mutation defait le
    precedent progres.
    """
    locked = set(locked or ())
    rng = np.random.default_rng(seed)
    out = SfxParams.from_dict(p.to_dict())
    out.seed = int(seed)

    for key, (lo, hi) in BOUNDS.items():
        if key in locked:
            continue
        span = (hi - lo) * float(amount)
        value = getattr(p, key) + rng.normal(0.0, span / 3.0)
        setattr(out, key, _clamp(key, value))

    if "arp_steps" not in locked and p.arp_steps and rng.random() < amount:
        out.arp_steps = tuple(int(_clamp("instrument", 0) * 0 + s +
                                 rng.integers(-2, 3)) for s in p.arp_steps)
    return out
```

- [ ] **Step 4 : lancer les tests**

Run: `python3 -m tests.test_design`
Expected: les 11 tests `OK`. Si `test_every_category_fits_the_budget` échoue, resserrer la plage `decay_frames` de la catégorie fautive — c'est le paramètre qui pèse le plus sur le nombre de commandes.

- [ ] **Step 5 : lancer toute la suite et committer**

```bash
python3 -m tests
git add to8sfx/design.py tests/test_design.py
git commit -m "feat(design): categories de jeu, tirage au sort, mutation a cadenas"
```

---

### Task 5 : la banque et l'export des deux fichiers assembleur

**Files:**
- Create: `to8sfx/bank.py`
- Create: `tests/test_bank.py`
- Modify: `tests/__main__.py:6`

**Interfaces:**
- Consumes: `design.SfxParams`, `design.render`, `codegen.fit_to_budget`, `codegen.stats`, `codegen.to_asm`, `rhythm.check_channel`
- Produces:
  - `bank.BankSound` (dataclass : `name`, `params`, `category`, `channel: int | None`, `priority: int`)
  - `bank.Bank` (dataclass : `name`, `default_channel`, `sounds`)
  - `bank.Bank.channel_of(s) -> int`
  - `bank.Bank.build() -> dict` avec les clés `asm`, `const`, `bytes`, `per_sound`, `warnings`
  - `bank.Bank.to_json() -> str`, `bank.Bank.from_json(text) -> Bank`

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_bank.py` :

```python
"""La banque : deux fichiers assembleur qui doivent rester d'accord.

L'ordre de soundFX.soundTable et celui des `equ` de soundFX.const.asm doivent
coincider. Une divergence ne se voit pas au build : le mauvais son se joue, sans
la moindre erreur. C'est la classe de bug que la banque existe pour supprimer.
"""

import re
import sys

from to8sfx import bank, codegen, design, importer


def _bank():
    b = bank.Bank(name="essai", default_channel=4)
    b.sounds.append(bank.BankSound(name="Laser", category="tir",
                                   params=design.randomize("tir", seed=1)))
    b.sounds.append(bank.BankSound(name="Boum", category="explosion",
                                   params=design.randomize("explosion", seed=2)))
    b.sounds.append(bank.BankSound(name="Piece", category="ramassage",
                                   params=design.randomize("ramassage", seed=3),
                                   channel=2))
    return b


def test_table_and_constants_agree():
    out = _bank().build()
    table = re.findall(r"fdb\s+soundFX\.(\w+)\.data", out["asm"])
    consts = re.findall(r"soundFX\.(\w+)\s+equ\s+(\d+)", out["const"])
    assert table == ["Laser", "Boum", "Piece"], table
    assert consts == [("Laser", "0"), ("Boum", "1"), ("Piece", "2")], consts
    print(f"  table {table} et constantes d'accord")


def test_blocks_round_trip_through_the_parser():
    """Relire ce qu'on vient d'ecrire : les tailles et la voie doivent coller."""
    b = _bank()
    out = b.build()
    for entry in out["per_sound"]:
        channel, cmds = importer.parse_asm_sound(out["asm"],
                                                 f"soundFX.{entry['name']}.data")
        assert channel == entry["channel"], (
            f"{entry['name']} : voie {channel} relue, {entry['channel']} ecrite")
        assert len(cmds) == entry["commands"], (
            f"{entry['name']} : {len(cmds)} commandes relues, "
            f"{entry['commands']} annoncees")
    print(f"  {len(out['per_sound'])} blocs relus, tailles et voies conformes")


def test_per_sound_channel_overrides_the_default():
    out = _bank().build()
    by_name = {e["name"]: e for e in out["per_sound"]}
    assert by_name["Laser"]["channel"] == 4, "la voie par defaut n'est pas prise"
    assert by_name["Piece"]["channel"] == 2, "la surcharge par son n'est pas prise"
    print("  voie par defaut 4, surcharge a 2 sur un son")


def test_noise_layer_refuses_a_channel_above_six():
    b = bank.Bank(default_channel=8)
    p = design.randomize("explosion", seed=5)
    p.noise_on = True
    b.sounds.append(bank.BankSound(name="Boum", category="explosion", params=p))
    try:
        b.build()
    except ValueError as exc:
        assert "voie" in str(exc).lower()
        print("  couche bruit refusee sur la voie 8")
        return
    raise AssertionError("voie 8 acceptee avec la couche bruit")


def test_duplicate_names_are_refused():
    b = _bank()
    b.sounds.append(bank.BankSound(name="Laser", category="tir",
                                   params=design.randomize("tir", seed=9)))
    try:
        b.build()
    except ValueError as exc:
        assert "Laser" in str(exc)
        print("  nom en double refuse")
        return
    raise AssertionError("nom en double accepte : deux equ pour deux ids")


def test_json_round_trip():
    b = _bank()
    again = bank.Bank.from_json(b.to_json())
    assert again.default_channel == b.default_channel
    assert [s.name for s in again.sounds] == [s.name for s in b.sounds]
    assert again.sounds[0].params.to_dict() == b.sounds[0].params.to_dict()
    print("  aller-retour JSON conforme")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n  {e}")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2 : lancer les tests pour les voir échouer**

Run: `python3 -m tests.test_bank`
Expected: `ModuleNotFoundError: No module named 'to8sfx.bank'`

- [ ] **Step 3 : écrire `to8sfx/bank.py`**

```python
"""La banque de bruitages, et les deux fichiers assembleur qu'elle produit.

soundFX.asm porte la table et les blocs de donnees ; soundFX.const.asm porte
les identifiants. L'ordre de la table et celui des `equ` DOIVENT coincider :
une divergence ne se voit pas au build, elle joue simplement le mauvais son.
Les tenir a la main est une source de bug silencieux ; c'est la raison d'etre
de ce module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import codegen, design, rhythm

NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


@dataclass
class BankSound:
    name: str
    params: design.SfxParams
    category: str = ""
    channel: int | None = None  # None = voie par defaut de la banque
    priority: int = 1


@dataclass
class Bank:
    name: str = "banque"
    default_channel: int = 4
    sounds: list[BankSound] = field(default_factory=list)

    def channel_of(self, s: BankSound) -> int:
        return self.default_channel if s.channel is None else int(s.channel)

    # --- serialisation ---

    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "default_channel": self.default_channel,
            "sounds": [{"name": s.name, "category": s.category,
                        "channel": s.channel, "priority": s.priority,
                        "params": s.params.to_dict()} for s in self.sounds],
        }, indent=2)

    @staticmethod
    def from_json(text: str) -> "Bank":
        d = json.loads(text)
        b = Bank(name=d.get("name", "banque"),
                 default_channel=int(d.get("default_channel", 4)))
        for s in d.get("sounds", []):
            b.sounds.append(BankSound(
                name=s["name"],
                params=design.SfxParams.from_dict(s.get("params", {})),
                category=s.get("category", ""),
                channel=s.get("channel"),
                priority=int(s.get("priority", 1)),
            ))
        return b

    # --- generation ---

    def _validate(self) -> None:
        seen = set()
        for s in self.sounds:
            if not s.name or any(c not in NAME_OK for c in s.name):
                raise ValueError(
                    f"nom de son invalide : {s.name!r}. Il devient une etiquette "
                    "assembleur, donc lettres, chiffres et souligne seulement.")
            if s.name in seen:
                raise ValueError(
                    f"nom en double : {s.name}. Deux `equ` porteraient le meme "
                    "nom pour deux identifiants differents.")
            seen.add(s.name)
            if s.params.noise_on:
                rhythm.check_channel(self.channel_of(s))

    def build(self) -> dict:
        """Produit les deux fichiers et le detail par son."""
        self._validate()

        blocks: list[str] = []
        per_sound: list[dict] = []
        warnings: list[str] = []
        total = 0

        for i, s in enumerate(self.sounds):
            channel = self.channel_of(s)
            frames, noise = design.render(s.params)
            cmds, _used, info = codegen.fit_to_budget(
                frames, noise=noise, channel=channel,
                noise_pitch=s.params.noise_pitch, noise_vol=s.params.noise_vol,
                quantize_pitch=True)
            st = codegen.stats(cmds)
            total += st["bytes"]

            source = f"{s.category or 'creation'}, graine {s.params.seed}"
            block = codegen.to_asm(s.name, channel, cmds, priority=s.priority,
                                   source=source)
            if s.params.noise_on:
                block = block.replace(
                    f"; {s.name} - genere par to8-soundfx-generator",
                    f"; {s.name} - genere par to8-soundfx-generator\n"
                    ";\n"
                    "; ATTENTION : ce son utilise la section RYTHME du YM2413.\n"
                    "; Le registre $0E requisitionne les voies 6, 7 et 8 de la\n"
                    "; puce. Si la musique du jeu s'en sert, son etat de batterie\n"
                    "; sera ecrase pendant la duree du bruitage.", 1)
            blocks.append(block)

            if info["truncated"]:
                warnings.append(
                    f"{s.name} : TRONQUE, il depasse 255 commandes meme simplifie "
                    "au maximum. Raccourcir la chute.")
            per_sound.append({
                "index": i, "name": s.name, "channel": channel,
                "priority": s.priority, "category": s.category,
                "commands": st["commands"], "bytes": st["bytes"],
                "seconds": round(st["seconds"], 2), "truncated": info["truncated"],
            })

        head = [
            f"; Banque {self.name} - genere par to8-soundfx-generator",
            f"; {len(self.sounds)} son(s), {total} octets de donnees",
            ";",
            "; L'ordre de cette table EST l'ordre des identifiants de",
            "; soundFX.const.asm. Ne pas reordonner l'un sans l'autre.",
            "",
            "soundFX.soundTable",
        ]
        for i, s in enumerate(self.sounds):
            head.append(f"            fdb     soundFX.{s.name}.data"
                        f"{' ' * max(1, 24 - len(s.name))}; {i} - "
                        f"{s.category or 'creation'}, voie {self.channel_of(s)}")
        asm = "\n".join(head) + "\n\n" + "\n".join(blocks)

        const = [
            f"; Identifiants de la banque {self.name}",
            "; Meme ordre que soundFX.soundTable.",
            "",
        ]
        for i, s in enumerate(self.sounds):
            const.append(f"soundFX.{s.name}{' ' * max(1, 24 - len(s.name))}equ {i}")
        return {
            "asm": asm,
            "const": "\n".join(const) + "\n",
            "bytes": total,
            "per_sound": per_sound,
            "warnings": warnings,
        }
```

- [ ] **Step 4 : brancher le fichier de test et lancer**

Dans `tests/__main__.py`, ajouter `"tests.test_bank"` après `"tests.test_design"`.

Run: `python3 -m tests.test_bank`
Expected: les 6 tests `OK`.

- [ ] **Step 5 : lancer toute la suite et committer**

```bash
python3 -m tests
git add to8sfx/bank.py tests/test_bank.py tests/__main__.py
git commit -m "feat(banque): banque de bruitages et export des deux fichiers assembleur"
```

---

### Task 6 : les endpoints du serveur

**Files:**
- Modify: `to8sfx/server.py` (imports, `STATE`, nouvelle fonction `_render_design`, routage `do_GET`/`do_POST`)
- Create: `tests/test_server_design.py`
- Modify: `tests/__main__.py:6`

**Interfaces:**
- Consumes: `design`, `bank`, `codegen`, `importer`, `opll`
- Produces (endpoints) :
  - `GET  /api/design/init` → `{categories, instruments, kits, bounds, defaults}`
  - `POST /api/design/random` `{category, seed}` → sortie de `_render_design`
  - `POST /api/design/mutate` `{params, amount, locked, seed, count}` → `{variants: [{params, stats, preview}]}`
  - `POST /api/design/render` `{params, channel, name, priority}` → sortie de `_render_design`
  - `GET  /api/variant.wav?i=N` → wav de la variante N
  - `GET  /api/bank` → `{name, default_channel, sounds, build}`
  - `POST /api/bank/add` `{name, category, params, channel, priority}` → `/api/bank`
  - `POST /api/bank/remove` `{index}` → `/api/bank`
  - `POST /api/bank/settings` `{name, default_channel}` → `/api/bank`

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_server_design.py` :

```python
"""Les endpoints de creation, appeles en direct (sans reseau).

On instancie le serveur pour de vrai serait plus lourd que necessaire : les
fonctions de traitement sont testables telles quelles, et c'est la ou vit la
logique.
"""

import sys

from to8sfx import bank, design, server


def test_render_design_returns_everything_the_ui_needs():
    p = design.randomize("tir", seed=11)
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Laser", "priority": 1})
    for key in ("asm", "stats", "curves", "preview", "warnings", "params"):
        assert key in out, f"cle absente de la reponse : {key}"
    assert out["stats"]["commands"] > 0
    assert len(out["curves"]["freq"]) == p.duration_frames
    assert "soundFX.Laser.data" in out["asm"]
    print(f"  {out['stats']['commands']} commandes, {out['stats']['bytes']} octets")


def test_noise_layer_warns_about_the_music():
    p = design.randomize("explosion", seed=4)
    p.noise_on = True
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Boum", "priority": 1})
    joined = " ".join(out["warnings"]).lower()
    assert "rythme" in joined and ("6" in joined or "musique" in joined), out["warnings"]
    print("  avertissement de la couche bruit present")


def test_bank_endpoints_keep_state():
    server.STATE["bank"] = bank.Bank(default_channel=4)
    p = design.randomize("tir", seed=2)
    server._bank_add({"name": "Laser", "category": "tir", "params": p.to_dict()})
    server._bank_add({"name": "Boum", "category": "explosion",
                      "params": design.randomize("explosion", seed=3).to_dict()})
    view = server._bank_view()
    assert len(view["sounds"]) == 2, view["sounds"]
    assert view["build"]["bytes"] > 0
    server._bank_remove({"index": 0})
    view = server._bank_view()
    assert [s["name"] for s in view["sounds"]] == ["Boum"], view["sounds"]
    print(f"  banque : ajout, vue, retrait ; {view['build']['bytes']} octets")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}\n  {e}")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `python3 -m tests.test_server_design`
Expected: `AttributeError: module 'to8sfx.server' has no attribute '_render_design'`

- [ ] **Step 3 : ajouter les fonctions de traitement à `to8sfx/server.py`**

Dans les imports, remplacer :

```python
from . import codegen, importer, instruments, melody, opll, parametric
```

par :

```python
from . import bank as bank_mod
from . import codegen, design, importer, instruments, melody, opll
```

Dans `STATE`, ajouter deux clés :

```python
    "variant_wavs": [],
    "bank": None,
```

Ajouter, juste avant la section `# --- HTTP ---` :

```python
# --- Creation ---------------------------------------------------------------


def _render_design(params: dict) -> dict:
    """Rend un jeu de parametres : assembleur, statistiques, courbes, preview."""
    p = design.SfxParams.from_dict(params.get("params") or {})
    channel = int(params.get("channel", 4))
    name = params.get("name") or "NewSound"
    priority = int(params.get("priority", 1))

    warnings: list[str] = []
    if p.noise_on:
        warnings.append(
            "Couche bruit ACTIVE : le registre $0E bascule la puce en mode "
            "rythme et requisitionne les voies 6, 7 et 8. Si la musique du jeu "
            "s'en sert — c'est le cas de battlesquadron — son etat de batterie "
            "sera ecrase pendant le bruitage. Voies utilisables : 0 a "
            f"{rhythm_max()}."
        )

    frames, noise = design.render(p)
    cmds, used, info = codegen.fit_to_budget(
        frames, noise=noise, channel=channel,
        noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
    st = codegen.stats(cmds)

    if info["cents"] > 0 or info["vol_step"] > 1:
        warnings.append(
            f"Simplifie pour tenir dans les 255 commandes : hauteur quantifiee a "
            f"{info['cents']:.0f} cents, volume par pas de {info['vol_step']}.")
    if info["truncated"]:
        warnings.append(
            "Son TRONQUE : meme simplifie au maximum il depasse 255 commandes. "
            "Raccourcir la chute.")

    ev, nsamples = codegen.commands_to_events(cmds, channel)
    y = opll.render(ev, nsamples)
    with LOCK:
        STATE["counter"] += 1
        STATE["preview_wav"] = importer.wav_bytes(y)

    return {
        "params": p.to_dict(),
        "asm": codegen.to_asm(name, channel, cmds, priority=priority,
                              source=f"creation, graine {p.seed}"),
        "stats": st,
        "info": info,
        "warnings": warnings,
        "curves": {
            "freq": [round(opll.fnum_block_to_freq(f.fnum, f.block), 2) for f in used],
            "volume": [f.volume for f in used],
            "noise": list(noise) if noise else [],
        },
        "preview": f"/api/preview.wav?t={STATE['counter']}",
        "const_line": f"soundFX.{name:22s} equ <id>",
        "call_line": f"        _soundFX.play soundFX.{name},{priority}",
    }


def rhythm_max() -> int:
    from . import rhythm
    return rhythm.MAX_CHANNEL


def _variants(params: dict) -> dict:
    """Huit mutations du son courant, chacune avec son wav pret a ecouter."""
    base = design.SfxParams.from_dict(params.get("params") or {})
    amount = float(params.get("amount", 0.3))
    locked = set(params.get("locked") or ())
    seed0 = int(params.get("seed", 0))
    count = int(params.get("count", 8))
    channel = int(params.get("channel", 4))

    out = []
    wavs = []
    for k in range(count):
        p = design.mutate(base, amount, locked, seed=seed0 + k + 1)
        frames, noise = design.render(p)
        try:
            cmds, _u, _i = codegen.fit_to_budget(
                frames, noise=noise, channel=channel,
                noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
        except ValueError:
            # voie incompatible avec la couche bruit : la variante est ecartee
            continue
        ev, n = codegen.commands_to_events(cmds, channel)
        wavs.append(importer.wav_bytes(opll.render(ev, n)))
        st = codegen.stats(cmds)
        out.append({"params": p.to_dict(), "stats": st,
                    "preview": f"/api/variant.wav?i={len(wavs) - 1}"})
    with LOCK:
        STATE["variant_wavs"] = wavs
    return {"variants": out}


def _bank() -> "bank_mod.Bank":
    if STATE.get("bank") is None:
        STATE["bank"] = bank_mod.Bank()
    return STATE["bank"]


def _bank_view() -> dict:
    b = _bank()
    try:
        built = b.build()
    except ValueError as exc:
        built = {"asm": "", "const": "", "bytes": 0, "per_sound": [],
                 "warnings": [str(exc)]}
    return {
        "name": b.name,
        "default_channel": b.default_channel,
        "sounds": [{"name": s.name, "category": s.category,
                    "channel": s.channel, "priority": s.priority,
                    "params": s.params.to_dict()} for s in b.sounds],
        "build": built,
    }


def _bank_add(params: dict) -> dict:
    b = _bank()
    b.sounds.append(bank_mod.BankSound(
        name=params.get("name") or f"Son{len(b.sounds)}",
        params=design.SfxParams.from_dict(params.get("params") or {}),
        category=params.get("category", ""),
        channel=params.get("channel"),
        priority=int(params.get("priority", 1)),
    ))
    return _bank_view()


def _bank_remove(params: dict) -> dict:
    b = _bank()
    i = int(params.get("index", -1))
    if 0 <= i < len(b.sounds):
        b.sounds.pop(i)
    return _bank_view()


def _bank_settings(params: dict) -> dict:
    b = _bank()
    if params.get("name"):
        b.name = str(params["name"])
    if params.get("default_channel") is not None:
        b.default_channel = int(params["default_channel"])
    return _bank_view()
```

- [ ] **Step 4 : brancher les routes**

Dans `do_GET`, avant le `return self._json({"error": "not found"}, 404)` final :

```python
        if path == "/api/design/init":
            from . import rhythm
            return self._json({
                "categories": {k: v["label"] for k, v in design.CATEGORIES.items()},
                "instruments": opll.INSTRUMENTS,
                "kits": list(rhythm.KIT_ORDER),
                "bounds": design.BOUNDS,
                "int_params": sorted(design.INT_PARAMS),
                "max_noise_channel": rhythm.MAX_CHANNEL,
                "defaults": design.SfxParams().to_dict(),
            })
        if path == "/api/bank":
            return self._json(_bank_view())
        if path == "/api/variant.wav":
            from urllib.parse import parse_qs
            i = int(parse_qs(urlparse(self.path).query).get("i", ["-1"])[0])
            wavs = STATE.get("variant_wavs") or []
            if not 0 <= i < len(wavs):
                return self._json({"error": "variante inconnue"}, 404)
            return self._send(200, wavs[i], "audio/wav")
```

Dans `do_POST`, à l'intérieur du `try`, après le bloc `/api/generate` :

```python
            if path == "/api/design/random":
                params = json.loads(body or b"{}")
                p = design.randomize(params.get("category", "tir"),
                                     int(params.get("seed", 0)))
                return self._json(_render_design({**params, "params": p.to_dict()}))

            if path == "/api/design/render":
                return self._json(_render_design(json.loads(body or b"{}")))

            if path == "/api/design/mutate":
                return self._json(_variants(json.loads(body or b"{}")))

            if path == "/api/bank/add":
                return self._json(_bank_add(json.loads(body or b"{}")))

            if path == "/api/bank/remove":
                return self._json(_bank_remove(json.loads(body or b"{}")))

            if path == "/api/bank/settings":
                return self._json(_bank_settings(json.loads(body or b"{}")))
```

- [ ] **Step 5 : brancher le fichier de test et lancer**

Dans `tests/__main__.py`, ajouter `"tests.test_server_design"` après `"tests.test_bank"`.

Run: `python3 -m tests.test_server_design && python3 -m tests`
Expected: aucun `FAIL`.

- [ ] **Step 6 : vérifier le serveur en vrai**

```bash
python3 cli.py ui --port 8815 --no-browser &
curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:8815/
curl -s http://127.0.0.1:8815/api/design/init | head -c 200; echo
printf '%s' '{"category":"explosion","seed":42,"channel":4,"name":"Boum"}' > /tmp/req.json
curl -s -X POST http://127.0.0.1:8815/api/design/random \
     -H 'Content-Type: application/json' --data-binary @/tmp/req.json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['stats'], d['warnings'])"
kill %1
```

Expected: `init` renvoie les catégories, `random` renvoie des statistiques non nulles.

- [ ] **Step 7 : commit**

```bash
git add to8sfx/server.py tests/test_server_design.py tests/__main__.py
git commit -m "feat(serveur): endpoints de creation, de mutation et de banque"
```

---

### Task 7 : l'onglet Créer

**Files:**
- Modify: `static/index.html:75-77` (les onglets), `static/index.html:313-320` (la bascule), et ajout d'un panneau

**Interfaces:**
- Consumes: `/api/design/init`, `/api/design/random`, `/api/design/render`, `/api/design/mutate`, `/api/bank*`
- Produces: rien pour les autres tâches.

- [ ] **Step 1 : remplacer l'onglet Paramétrique**

Remplacer le bloc des onglets :

```html
  <div class="tabs">
    <button id="tabParam" class="on">Param&eacute;trique</button>
    <button id="tabWav">Fichier audio</button>
  </div>
```

par :

```html
  <div class="tabs">
    <button id="tabCreate" class="on">Cr&eacute;er</button>
    <button id="tabWav">Fichier audio</button>
  </div>
```

- [ ] **Step 2 : remplacer le panneau Paramétrique par le panneau Créer**

Repérer le conteneur du mode paramétrique (celui masqué/affiché par `tabParam`) et le remplacer par :

```html
<div id="panCreate">
  <fieldset><legend>Cat&eacute;gorie</legend>
    <div id="cats" class="row" style="flex-wrap:wrap;gap:6px"></div>
    <button id="roll" style="width:100%;margin-top:10px;padding:10px;font-weight:600">
      TIRER AU SORT
    </button>
    <label style="margin-top:10px">Force de la mutation <span id="vAmt">30</span> %</label>
    <input type="range" id="amount" min="5" max="100" step="5" value="30">
    <button id="mutate" style="width:100%;padding:8px">MUTER &mdash; 8 variantes</button>
    <div id="variants" class="row" style="flex-wrap:wrap;gap:4px;margin-top:8px"></div>
    <div class="hint">Clic = &eacute;couter, re-clic = adopter.</div>
  </fieldset>

  <fieldset><legend>Affiner</legend>
    <div class="hint">Le cadenas emp&ecirc;che la mutation de toucher un r&eacute;glage.
      C'est comme &ccedil;a qu'on converge&nbsp;: on fige ce qui est bon, on relance
      le hasard sur le reste.</div>
    <div id="sliders"></div>
  </fieldset>

  <fieldset><legend>Couche bruit &mdash; section rythme</legend>
    <label style="display:flex;gap:8px;align-items:center;margin-top:0">
      <input type="checkbox" id="noise_on" style="width:auto"> Activer les percussions
    </label>
    <div class="hint"><b>Attention</b>&nbsp;: le registre $0E requisitionne les voies
      6, 7 et 8 de la puce. Si la musique du jeu s'en sert &mdash; c'est le cas de
      battlesquadron &mdash; son &eacute;tat de batterie sera &eacute;cras&eacute; pendant le
      bruitage. Voies utilisables&nbsp;: 0 &agrave; 5.</div>
    <div id="kit" class="row" style="flex-wrap:wrap;gap:6px"></div>
  </fieldset>

  <fieldset><legend>Banque</legend>
    <div class="row">
      <div><label>Nom du son</label><input type="text" id="sndName" value="NewSound"></div>
      <div><label>Voie YM2413</label><input type="number" id="sndChannel" min="0" max="8"></div>
    </div>
    <div class="hint">Vide = la voie par d&eacute;faut de la banque. L'outil ne peut pas
      deviner ce que la musique de ton jeu occupe.</div>
    <button id="keep" style="width:100%;padding:8px;margin-top:8px">GARDER DANS LA BANQUE</button>
    <div class="row" style="margin-top:10px">
      <div><label>Voie par d&eacute;faut</label><input type="number" id="bankChannel" min="0" max="8" value="4"></div>
      <div><label>Nom de la banque</label><input type="text" id="bankName" value="banque"></div>
    </div>
    <div id="bankList" class="rank" style="margin-top:8px"></div>
  </fieldset>
</div>
```

- [ ] **Step 3 : écrire le JavaScript du panneau**

Ajouter, dans la balise `<script>` existante :

```javascript
let INIT = null, CUR = null, LOCKED = new Set(), CAT = 'tir', VARIANTS = [], playing = -1;

async function initCreate(){
  INIT = await (await fetch('/api/design/init')).json();
  const cats = $('cats');
  for (const [k, label] of Object.entries(INIT.categories)){
    const b = document.createElement('button');
    b.textContent = label; b.dataset.k = k;
    b.style.cssText = 'flex:1 0 30%;padding:6px';
    b.onclick = () => { CAT = k; paintCats(); roll(); };
    cats.appendChild(b);
  }
  paintCats();
  buildSliders();
  const kit = $('kit');
  for (const k of INIT.kits){
    const l = document.createElement('label');
    l.style.cssText = 'display:flex;gap:4px;align-items:center;flex:1 0 30%';
    l.innerHTML = `<input type="checkbox" data-kit="${k}" style="width:auto"> ${k}`;
    kit.appendChild(l);
  }
  await roll();
  await refreshBank();
}

function paintCats(){
  for (const b of $('cats').children) b.classList.toggle('on', b.dataset.k === CAT);
}

function buildSliders(){
  const box = $('sliders');
  box.innerHTML = '';
  for (const [key, [lo, hi]] of Object.entries(INIT.bounds)){
    const isInt = INIT.int_params.includes(key);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:6px;align-items:center;margin:2px 0';
    row.innerHTML =
      `<input type="checkbox" data-lock="${key}" title="cadenas" style="width:auto">` +
      `<label style="flex:0 0 130px;margin:0;font-size:11px">${key}</label>` +
      `<input type="range" data-p="${key}" min="${lo}" max="${hi}" ` +
      `step="${isInt ? 1 : (hi - lo) / 200}" style="flex:1">` +
      `<span data-v="${key}" style="flex:0 0 52px;text-align:right;font-size:11px"></span>`;
    box.appendChild(row);
  }
  box.oninput = e => {
    if (e.target.dataset.p){ CUR[e.target.dataset.p] = +e.target.value; render(); }
  };
  box.onchange = e => {
    const k = e.target.dataset.lock;
    if (k) { e.target.checked ? LOCKED.add(k) : LOCKED.delete(k); }
  };
}

function paintParams(){
  for (const [key] of Object.entries(INIT.bounds)){
    const s = document.querySelector(`[data-p="${key}"]`);
    const v = document.querySelector(`[data-v="${key}"]`);
    if (s) s.value = CUR[key];
    if (v) v.textContent = (+CUR[key]).toFixed(
      INIT.int_params.includes(key) ? 0 : 2);
  }
  $('noise_on').checked = !!CUR.noise_on;
  for (const c of document.querySelectorAll('[data-kit]'))
    c.checked = (CUR.noise_kit || []).includes(c.dataset.kit);
}

async function post(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                             body: JSON.stringify(body)});
  return r.json();
}

async function roll(){
  const d = await post('/api/design/random',
    {category: CAT, seed: Math.floor(Math.random()*1e6), channel: chan(), name: name_()});
  CUR = d.params; paintParams(); show(d); play(d.preview);
}

async function render(){
  const d = await post('/api/design/render',
    {params: CUR, channel: chan(), name: name_(), priority: 1});
  show(d); play(d.preview);
}

async function mutate(){
  const d = await post('/api/design/mutate',
    {params: CUR, amount: +$('amount').value/100, locked: [...LOCKED],
     seed: Math.floor(Math.random()*1e6), count: 8, channel: chan()});
  VARIANTS = d.variants;
  const box = $('variants'); box.innerHTML = ''; playing = -1;
  VARIANTS.forEach((v, i) => {
    const b = document.createElement('button');
    b.textContent = (i+1) + ' ▸'; b.style.cssText = 'flex:1 0 20%;padding:6px';
    b.onclick = () => {
      if (playing === i){ CUR = v.params; paintParams(); render(); }
      else { playing = i; play(v.preview); }
    };
    box.appendChild(b);
  });
}

function chan(){ const v = $('sndChannel').value; return v === '' ? +$('bankChannel').value : +v; }
function name_(){ return $('sndName').value || 'NewSound'; }

async function refreshBank(){
  const b = await (await fetch('/api/bank')).json();
  const el = $('bankList');
  el.innerHTML = b.sounds.length ? '' : '<i>banque vide</i>';
  b.build.per_sound.forEach(s => {
    const d = document.createElement('div');
    d.textContent = `${s.index} ${s.name} — voie ${s.channel}, ${s.commands} cmd, ${s.bytes} o`
      + (s.truncated ? '  ⚠ TRONQUE' : '');
    el.appendChild(d);
  });
  if (b.sounds.length){
    const t = document.createElement('div');
    t.style.marginTop = '6px';
    t.textContent = `total ${b.build.bytes} octets`;
    el.appendChild(t);
  }
  (b.build.warnings || []).forEach(w => {
    const d = document.createElement('div'); d.style.color = '#e8a33d'; d.textContent = '⚠ ' + w;
    el.appendChild(d);
  });
}

$('roll').onclick = roll;
$('mutate').onclick = mutate;
$('amount').oninput = () => { $('vAmt').textContent = $('amount').value; };
$('noise_on').onchange = e => { CUR.noise_on = e.target.checked; render(); };
$('kit').onchange = () => {
  CUR.noise_kit = [...document.querySelectorAll('[data-kit]')]
    .filter(c => c.checked).map(c => c.dataset.kit);
  render();
};
$('keep').onclick = async () => {
  await post('/api/bank/add', {name: name_(), category: CAT, params: CUR,
                               channel: $('sndChannel').value === '' ? null : chan(),
                               priority: 1});
  await refreshBank();
};
$('bankChannel').onchange = $('bankName').onchange = async () => {
  await post('/api/bank/settings', {name: $('bankName').value,
                                    default_channel: +$('bankChannel').value});
  await refreshBank();
};
document.addEventListener('keydown', e => {
  if (e.code === 'Space' && e.target.tagName !== 'INPUT'){ e.preventDefault(); render(); }
});
```

`show(d)` et `play(url)` sont les fonctions déjà présentes qui peignent la sortie et lancent l'audio ; les réutiliser telles quelles. Si leurs noms diffèrent dans le fichier, adapter les appels plutôt que de les dupliquer.

- [ ] **Step 4 : adapter la bascule d'onglets**

Remplacer les gestionnaires `tabParam` / `tabWav` par :

```javascript
$('tabCreate').onclick = ()=>{ mode='create'; $('tabCreate').classList.add('on');
  $('tabWav').classList.remove('on'); $('panCreate').classList.remove('hide');
  $('panWav').classList.add('hide'); };
$('tabWav').onclick = ()=>{ mode='wav'; $('tabWav').classList.add('on');
  $('tabCreate').classList.remove('on'); $('panWav').classList.remove('hide');
  $('panCreate').classList.add('hide'); };
```

et appeler `initCreate()` au chargement, à côté de l'initialisation existante.

- [ ] **Step 5 : vérifier à la main**

```bash
python3 cli.py ui --port 8817
```

Vérifier, dans l'ordre : l'onglet Créer s'ouvre par défaut ; **Tirer au sort** produit un son différent à chaque clic et il se joue ; **Muter** affiche huit variantes, un clic les écoute, un second l'adopte ; un cadenas coché fige bien son curseur d'une mutation à l'autre ; **Garder dans la banque** ajoute une ligne avec sa voie et ses octets ; l'onglet **Fichier audio** fonctionne exactement comme avant.

- [ ] **Step 6 : commit**

```bash
git add static/index.html
git commit -m "feat(interface): onglet Creer, tirage au sort, mutation et banque"
```

---

### Task 8 : ligne de commande, retrait de `parametric.py`, README

**Files:**
- Modify: `cli.py` (retrait de `cmd_sweep`, ajout de `cmd_create` et `cmd_bank`)
- Delete: `to8sfx/parametric.py`
- Modify: `tests/test_melody.py` (le test du glissando utilise `parametric`)
- Modify: `to8sfx/server.py` (le mode `param` de `_build` disparaît)
- Modify: `README.md`

**Interfaces:**
- Consumes: `design`, `bank`
- Produces: `./cli.py create --category explosion --seed 42 -o son.asm`, `./cli.py bank <banque.json> --out-dir <dir>`

- [ ] **Step 1 : réécrire le test du glissando sans `parametric`**

Dans `tests/test_melody.py`, remplacer le corps de `test_glissando_is_not_collapsed` :

```python
    from to8sfx import design
    frames, _ = design.render(design.SfxParams(
        attack_frames=0, hold_frames=0, decay_frames=21,
        f_start=440.0, slide=1.14, slide_delta=0.0,
        vol_peak=3, vol_end=6, instrument=12))
```

(le reste du test est inchangé : `melody.quantize(frames)`, puis les trois assertions.)

- [ ] **Step 2 : lancer le test pour vérifier qu'il passe encore**

Run: `python3 -m tests.test_melody`
Expected: `test_glissando_is_not_collapsed` toujours `OK`, avec au moins 8 notes et une montée d'au moins 20 demi-tons.

- [ ] **Step 3 : retirer le mode paramétrique du serveur**

Dans `to8sfx/server.py`, fonction `_build`, supprimer la branche `else:` qui construit `parametric.SweepParams` et lever à la place :

```python
    else:
        raise ValueError(
            "mode inconnu : le mode parametrique a ete remplace par l'onglet "
            "Creer, qui passe par /api/design/*")
```

Retirer aussi `parametric` de la réponse de `/api/presets` (garder `instruments`, `scales`, `notes`).

- [ ] **Step 4 : remplacer `sweep` par `create` et `bank` dans `cli.py`**

Supprimer `cmd_sweep` et son sous-analyseur. Ajouter :

```python
def cmd_create(args):
    from to8sfx import design as dz
    p = dz.randomize(args.category, args.seed)
    frames, noise = dz.render(p)
    cmds, _used, info = codegen.fit_to_budget(
        frames, noise=noise, channel=args.channel,
        noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
    st = codegen.stats(cmds)
    asm = codegen.to_asm(args.name, args.channel, cmds, priority=args.priority,
                         source=f"{args.category}, graine {args.seed}")
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(asm)
        print(f"ecrit : {args.out}")
    else:
        print(asm)
    print(f"  {st['commands']} commandes / 255, {st['bytes']} octets, "
          f"{st['seconds']:.2f} s, voie {args.channel}", file=sys.stderr)
    if info["truncated"]:
        print("  TRONQUE : raccourcir la chute", file=sys.stderr)
    if args.wav:
        ev, n = codegen.commands_to_events(cmds, args.channel)
        importer.write_wav(args.wav, opll.render(ev, n))
        print(f"preview : {args.wav}", file=sys.stderr)


def cmd_bank(args):
    from to8sfx import bank as bk
    b = bk.Bank.from_json(open(args.source).read())
    out = b.build()
    os.makedirs(args.out_dir, exist_ok=True)
    for fname, key in (("soundFX.asm", "asm"), ("soundFX.const.asm", "const")):
        path = os.path.join(args.out_dir, fname)
        with open(path, "w") as fh:
            fh.write(out[key])
        print(f"ecrit : {path}")
    print(f"  {len(out['per_sound'])} son(s), {out['bytes']} octets")
    for w in out["warnings"]:
        print(f"  ! {w}", file=sys.stderr)
```

Ajouter `import os` en tête de `cli.py`, et les sous-analyseurs dans `main()` :

```python
    p = sub.add_parser("create", help="tirer un bruitage au sort")
    common(p)
    p.add_argument("--category", default="tir")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("bank", help="generer les deux .asm depuis une banque JSON")
    p.add_argument("source", help="fichier JSON de la banque")
    p.add_argument("--out-dir", default=".", dest="out_dir")
    p.set_defaults(func=cmd_bank)
```

Retirer aussi `cmd_presets` et son sous-analyseur, qui listaient les presets paramétriques.

- [ ] **Step 5 : supprimer `parametric.py` et vérifier qu'il ne reste aucune référence**

```bash
git rm to8sfx/parametric.py
grep -rn "parametric" --include=*.py --include=*.html . || echo "aucune reference restante"
python3 -m tests
```

Expected: `aucune reference restante`, et toute la suite `OK`.

- [ ] **Step 6 : mettre le README à jour**

Remplacer la section « Utilisation → Interface » et la section « Ce que c'est » pour dire que l'outil est d'abord un **atelier de création** : catégories, tirage au sort, mutation à cadenas, trois couches, banque. Ajouter une section **Couche bruit** portant la mesure de platitude spectrale (caisse claire 0,27, charleston 0,12, note mélodique 0,00), l'avertissement sur les voies 6-8 et la limite des voies 0 à 5, avec la mesure qui la justifie (une note mélodique sur la voie 6 tombe à un RMS nul dès que le mode rythme s'active). Corriger la ligne du tableau des contraintes qui affirme aujourd'hui « pas de générateur de bruit sur la voie mélodique → une explosion enregistrée ne se convertit pas » : la première moitié reste vraie, la conclusion ne l'est plus puisque la section rythme existe. Mettre à jour le compte de tests et l'arborescence du dossier.

- [ ] **Step 7 : commit**

```bash
git add -A
git commit -m "feat(cli): sous-commandes create et bank, retrait du mode parametrique"
```

---

## Auto-relecture

**Couverture de la spec.** Modèle de son à trois couches → tâches 1 à 3. Catégories, tirage, mutation, cadenas → tâche 4. Banque et deux fichiers cohérents → tâche 5. Interface (boucle de chasse, historique implicite via les variantes, barre d'espace) → tâches 6 et 7. Voie par son et voie par défaut → tâches 5, 6, 7. Garde-fous (couche bruit éteinte par défaut, voies 0-6, avertissement dans l'ASM) → tâches 1, 3, 5, 6. Absorption de `parametric.py` → tâche 8. Instrument custom hors périmètre : aucune tâche, conforme.

**Point non couvert, assumé.** La spec mentionne un « historique » des tirages. Il est rendu par la rangée de variantes, qui garde huit candidats à portée de clic, mais il n'y a pas de pile persistante. Si tu veux un vrai historique rechargeable, c'est une tâche 9 à ajouter — je l'ai laissée dehors pour ne pas gonfler la première version.

**Cohérence des types.** `noise` est partout `list[int] | None` ; `channel` un `int` ; `SfxParams.to_dict()` sérialise `arp_steps` et `noise_kit` en listes, `from_dict` les retuple. `fit_to_budget` garde son ordre de retour `(cmds, frames, info)`.
