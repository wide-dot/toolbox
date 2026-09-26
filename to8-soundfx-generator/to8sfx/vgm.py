"""Relecture d'un export VGM (DefleMask) vers le flux de commandes du driver.

Le pendant de `importer.py` : celui-la relit de l'assembleur, celui-ci relit du
VGM ; tous deux rendent des `codegen.Command`. Contrairement a `analyze.py`, il
n'y a rien a deviner ici — le VGM porte les ecritures de registres elles-memes.

Tout l'enjeu est dans trois conversions, et une erreur dans l'une d'elles ne
fait pas planter, elle produit un bruitage qui joue, faux :

- le VGM compte le temps en samples a 44100 Hz, le driver en ticks de 20 ms ;
- le VGM nomme la voie DANS le registre ($12 = voie 2), le driver AJOUTE la voie
  de sortie au registre qu'on lui donne ;
- le VGM a neuf voies, le driver une seule.
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass, field

from . import codegen, opll, rhythm
from .codegen import CMD_CUSTOM_PATCH, Command
from .opll import KEY_ON, REG_BLOCK, REG_FNUM_LO, REG_INST_VOL, REG_RHYTHM

# Le VGM compte en samples a 44100 Hz, le driver en ticks de 20 ms.
TICK_SAMPLES = 882
SAMPLE_RATE = 44100

# Les trois registres d'une voie melodique, dans l'ordre ou le driver les veut :
# instrument/volume, F-Num bas, puis block+key-on en dernier pour que la hauteur
# soit complete au moment ou la note demarre. Meme ordre que frames_to_commands.
VOICE_REGS = (REG_INST_VOL, REG_FNUM_LO, REG_BLOCK)

PATCH_REGS = range(0x00, 0x08)  # patch custom, GLOBAL a la puce


@dataclass
class VgmFile:
    """Un VGM deroule : les ecritures YM2413, datees en ticks de 20 ms."""

    writes: list[tuple[int, int, int]] = field(default_factory=list)  # (tick, reg, val)
    n_ticks: int = 0
    clock: int = 0
    has_rhythm: bool = False

    @property
    def seconds(self) -> float:
        return self.n_ticks / 50.0


@dataclass
class ChannelInfo:
    """De quoi choisir une voie sans l'ecouter une par une."""

    channel: int
    writes: int
    first_tick: int
    last_tick: int
    instruments: list[int]
    uses_custom: bool

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "writes": self.writes,
            "first_tick": self.first_tick,
            "last_tick": self.last_tick,
            "instruments": self.instruments,
            "instrument_names": [opll.INSTRUMENTS.get(i, "?") for i in self.instruments],
            "uses_custom": self.uses_custom,
        }


# --- Lecture du fichier -----------------------------------------------------


def _u32(data: bytes, off: int) -> int:
    """Champ d'en-tete, ou 0 s'il est au-dela de l'en-tete reellement present."""
    if off + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, off)[0]


# Les autres puces qu'un VGM peut porter, pour nommer celle qu'on a trouvee
# quand le YM2413 est absent : le cas reel est un export fait sur la mauvaise
# machine dans DefleMask, et le message doit dire quoi changer.
_OTHER_CHIPS = (
    (0x0C, "SN76489"),
    (0x2C, "YM2612"),
    (0x30, "YM2151"),
    (0x38, "SegaPCM"),
    (0x44, "RF5C68"),
    (0x48, "YM2203"),
    (0x4C, "YM2608"),
    (0x50, "YM2610"),
    (0x54, "YM3812"),
    (0x58, "YM3526"),
    (0x5C, "Y8950"),
    (0x60, "YMF262"),
    (0x74, "AY8910"),
)

# Nombre d'octets d'operande par opcode, pour les commandes qu'on ne fait que
# sauter. Les sauter correctement est vital : une taille fausse decale tout le
# flux qui suit, et les donnees seraient relues comme des opcodes.
_SKIP = {
    0x4F: 1,  # stereo Game Gear
    0x50: 1,  # SN76489
    0x68: 12,  # ecriture PCM RAM
    0x90: 4, 0x91: 4, 0x92: 5, 0x93: 10, 0x94: 1, 0x95: 4,  # flux DAC
}


def parse(data: bytes) -> VgmFile:
    """Deroule un `.vgm` ou `.vgz` et date chaque ecriture YM2413 en ticks."""
    if data[:2] == b"\x1f\x8b":  # .vgz : le meme format, gzippe
        data = gzip.decompress(data)
    if data[:4] != b"Vgm ":
        raise ValueError(
            "ce n'est pas un fichier VGM (l'identifiant 'Vgm ' est absent). "
            "Dans DefleMask : Fichier > Exporter > VGM.")

    version = _u32(data, 0x08)
    clock = _u32(data, 0x10)
    if clock == 0:
        autres = [nom for off, nom in _OTHER_CHIPS if _u32(data, off)]
        trouve = ", ".join(autres) if autres else "aucune puce reconnue"
        raise ValueError(
            f"ce VGM ne contient pas de YM2413 (puce trouvee : {trouve}). "
            "Le driver soundFX du TO8 pilote un YM2413 : dans DefleMask, "
            "composer sur un systeme qui l'emploie (Master System + FM) et "
            "reexporter.")

    offset = _u32(data, 0x34)
    pos = 0x40 if (version < 0x150 or offset == 0) else 0x34 + offset

    v = VgmFile(clock=clock)
    samples = 0
    while pos < len(data):
        code = data[pos]
        pos += 1

        if code == 0x51:  # ecriture YM2413 : la seule qui nous interesse
            reg, val = data[pos], data[pos + 1]
            pos += 2
            v.writes.append((samples // TICK_SAMPLES, reg, val))
            if reg == REG_RHYTHM and (val & rhythm.RHYTHM_ON):
                v.has_rhythm = True
            continue
        if code == 0x61:
            samples += struct.unpack_from("<H", data, pos)[0]
            pos += 2
            continue
        if code == 0x62:  # 1/60 s : l'export NTSC de DefleMask
            samples += 735
            continue
        if code == 0x63:  # 1/50 s : l'export PAL
            samples += 882
            continue
        if code == 0x66:  # fin des donnees
            break
        if code == 0x67:  # bloc de donnees : 0x66, type, taille sur 32 bits
            taille = struct.unpack_from("<I", data, pos + 2)[0]
            pos += 6 + (taille & 0x7FFFFFFF)
            continue
        if 0x70 <= code <= 0x7F:  # attente de n+1 samples
            samples += (code & 0x0F) + 1
            continue
        if 0x80 <= code <= 0x8F:  # DAC YM2612 puis attente de n samples
            samples += code & 0x0F
            continue
        if code in _SKIP:
            pos += _SKIP[code]
            continue
        # Les plages generiques du format : le nombre d'operandes se deduit de
        # l'opcode, ce qui permet de traverser une puce qu'on ne connait pas.
        if 0x30 <= code <= 0x3F:
            pos += 1
            continue
        if 0x40 <= code <= 0x4E:
            pos += 2 if version >= 0x160 else 1
            continue
        if 0x52 <= code <= 0x5F or 0xA0 <= code <= 0xBF:
            pos += 2
            continue
        if 0xC0 <= code <= 0xDF:
            pos += 3
            continue
        if 0xE0 <= code <= 0xFF:
            pos += 4
            continue

        raise ValueError(
            f"opcode VGM inconnu ${code:02X} a l'offset ${pos - 1:04X}. "
            "Le sauter desynchroniserait tout le flux qui suit : les donnees "
            "seraient relues comme des opcodes.")

    v.n_ticks = samples // TICK_SAMPLES
    return v


# --- Inventaire des voies ---------------------------------------------------


def _is_voice_reg(reg: int, channel: int) -> bool:
    """`reg` est-il un des trois registres melodiques de `channel` ?"""
    return (reg & 0x0F) == channel and (reg & 0xF0) in (0x10, 0x20, 0x30)


def survey(v: VgmFile) -> list[ChannelInfo]:
    """Activite par voie, pour que le choix se fasse a l'oeil et non a l'oreille."""
    out: list[ChannelInfo] = []
    for ch in range(rhythm.CHANNEL_MIN, rhythm.CHANNEL_MAX + 1):
        ticks = [t for t, reg, _ in v.writes if _is_voice_reg(reg, ch)]
        if not ticks:
            continue
        insts = sorted({val >> 4 for _, reg, val in v.writes
                        if reg == REG_INST_VOL + ch})
        out.append(ChannelInfo(
            channel=ch, writes=len(ticks),
            first_tick=min(ticks), last_tick=max(ticks),
            instruments=insts, uses_custom=0 in insts,
        ))
    return out


# --- Etat de la voie, tick par tick -----------------------------------------


def trace(v: VgmFile, channel: int, t0: int = 0, t1: int | None = None) -> list[dict]:
    """Hauteur, volume et key-on de `channel` pour chaque tick de la fenetre.

    Sert a VOIR la voie avant de la decouper : sans ca, choisir une fenetre dans
    un VGM de 77 secondes revient a tirer au hasard.
    """
    t1 = v.n_ticks if t1 is None else t1
    etat = {REG_FNUM_LO: 0, REG_BLOCK: 0, REG_INST_VOL: 0}
    out: list[dict] = []
    i = 0
    for tick in range(0, max(t1, 0)):
        while i < len(v.writes) and v.writes[i][0] <= tick:
            _, reg, val = v.writes[i]
            if _is_voice_reg(reg, channel):
                etat[reg & 0xF0] = val
            i += 1
        if tick < t0:
            continue
        haut = etat[REG_BLOCK]
        fnum = etat[REG_FNUM_LO] | ((haut & 1) << 8)
        block = (haut >> 1) & 7
        out.append({
            "hz": round(opll.fnum_block_to_freq(fnum, block), 2) if fnum else 0.0,
            "vol": etat[REG_INST_VOL] & 0x0F,
            "inst": etat[REG_INST_VOL] >> 4,
            "on": bool(haut & KEY_ON),
        })
    return out


# --- VGM -> commandes du driver ---------------------------------------------


def to_commands(v: VgmFile, channel: int, t0: int = 0,
                t1: int | None = None) -> tuple[list[Command], list[str]]:
    """Transcrit une voie melodique du VGM en flux de commandes du driver.

    Cinq etapes, dans cet ordre : filtrer la voie, amorcer l'etat des registres
    tel qu'il est a `t0`, rebaser les registres pour l'addition que fait le
    driver, dedupliquer, puis repartir les delais.

    Rend (commandes, avertissements). Les avertissements ne sont pas cosmetiques :
    une voie requisitionnee par le mode rythme est MUETTE, pas approximative.
    """
    t1 = v.n_ticks if t1 is None else t1
    rhythm.check_any_channel(channel)
    avis: list[str] = []

    if v.has_rhythm and channel > rhythm.MAX_CHANNEL:
        avis.append(
            f"voie {channel} MUETTE : ce VGM active la section rythme, qui "
            "requisitionne les voies 6, 7 et 8 de la puce. Choisir une voie de "
            f"0 a {rhythm.MAX_CHANNEL}.")
    if v.has_rhythm:
        avis.append(
            "ce VGM emploie la section rythme du YM2413 ; ces ecritures ne sont "
            "pas transcrites. Pour un bruitage percussif, passer par la couche "
            "bruit de l'onglet Creer.")

    # --- Etat des registres a t0, et patch custom courant ---
    etat: dict[int, int | None] = {r: None for r in VOICE_REGS}
    patch = [0] * 8
    fenetre = []
    for tick, reg, val in v.writes:
        if tick < t0:
            if reg in PATCH_REGS:
                patch[reg] = val
            elif _is_voice_reg(reg, channel):
                etat[reg & 0xF0] = val
        elif tick < t1:
            fenetre.append((tick, reg, val))

    # Le patch est-il necessaire, et dans quel etat ? Il l'est des que la voie
    # selectionne l'instrument 0, et sa valeur est celle des registres $00-$07
    # au moment ou ca arrive — les ecritures de patch precedent le changement
    # d'instrument dans le meme tick, c'est pour ca qu'on suit l'ordre du flux.
    patch_bytes: bytes | None = None
    if etat[REG_INST_VOL] is not None and (etat[REG_INST_VOL] >> 4) == 0:
        patch_bytes = bytes(patch)
    for _tick, reg, val in fenetre:
        if reg in PATCH_REGS:
            if patch_bytes is not None and patch[reg] != val:
                avis.append(
                    "le patch de l'instrument custom ($00-$07) change pendant la "
                    "fenetre choisie. Le bloc assembleur ne porte qu'UN patch : "
                    "le second changement sera perdu. Reduire la fenetre, ou "
                    "figer l'instrument dans DefleMask.")
                break
            patch[reg] = val
        elif reg == REG_INST_VOL + channel and (val >> 4) == 0 and patch_bytes is None:
            patch_bytes = bytes(patch)

    # --- Emissions datees : patch, amorcage, puis le flux de la fenetre ---
    emis: list[tuple[int, Command]] = []
    shadow: dict[int, int | None] = {r: None for r in VOICE_REGS}

    if patch_bytes is not None:
        # La commande $FF ecrit les 8 registres du patch PUIS selectionne
        # l'instrument 0 au volume 0 sur la voie : son effet sur $30 est connu,
        # donc on le porte dans le shadow pour ne pas le reecrire pour rien.
        emis.append((t0, Command(CMD_CUSTOM_PATCH, 0, 0, patch=patch_bytes)))
        shadow[REG_INST_VOL] = 0x00

    for reg in VOICE_REGS:  # amorcage, dans l'ordre du driver
        if etat[reg] is not None and etat[reg] != shadow[reg]:
            emis.append((t0, Command(reg, etat[reg], 0)))
            shadow[reg] = etat[reg]

    for tick, reg, val in fenetre:
        if not _is_voice_reg(reg, channel):
            continue
        base = reg & 0xF0  # le driver AJOUTE la voie de sortie : $12 -> $10
        if shadow[base] == val:
            continue  # DefleMask reecrit la hauteur a chaque ligne du tracker
        emis.append((tick, Command(base, val, 0)))
        shadow[base] = val

    if not emis:
        avis.append(
            f"la voie {channel} n'ecrit rien dans la fenetre choisie "
            f"(ticks {t0} a {t1}). Choisir une autre voie, ou elargir la fenetre.")
        return [], avis

    # --- Delais : jusqu'a l'ecriture suivante, et jusqu'a la fin pour la derniere ---
    cmds: list[Command] = []
    for i, (tick, cmd) in enumerate(emis):
        suivant = emis[i + 1][0] if i + 1 < len(emis) else max(t1, tick)
        reste = max(0, suivant - tick)
        cmd.delay = min(reste, codegen.MAX_DELAY)
        cmds.append(cmd)
        reste -= cmd.delay
        while reste > 0:
            # Delai sature : on reecrit un registre a l'identique, c'est
            # inoffensif et ca repart pour 255 ticks. Meme ruse que
            # frames_to_commands, et pour la meme raison : le champ delai tient
            # sur un seul octet.
            pas = min(reste, codegen.MAX_DELAY)
            cmds.append(Command(REG_FNUM_LO, shadow[REG_FNUM_LO] or 0, pas))
            reste -= pas

    if len(cmds) > codegen.MAX_COMMANDS:
        avis.append(
            f"{len(cmds)} commandes pour un maximum de {codegen.MAX_COMMANDS} : "
            "l'en-tete du bloc les compte sur un seul octet. Resserrer la "
            "fenetre de selection.")
    return cmds, avis
