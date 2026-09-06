"""Trames 50 Hz -> flux de commandes du driver -> code assembleur.

Tout l'interet du generateur est ici : une conversion naive ecrit deux commandes
par trame (6 octets toutes les 20 ms, soit 300 octets par seconde) et sature en
une seconde le compteur de commandes de l'en-tete, qui tient sur UN octet.

On n'ecrit donc un registre que quand sa valeur change vraiment, et on allonge
le delai de la commande precedente sinon. Sur un plateau de hauteur, une seule
commande peut couvrir 255 ticks (5 s).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import opll
from . import rhythm
from .opll import (
    KEY_ON,
    REG_BLOCK,
    REG_FNUM_LO,
    REG_INST_VOL,
    Frame,
    fnum_block_to_freq,
    freq_to_fnum_block,
)

MAX_COMMANDS = 255  # l'en-tete compte les commandes sur un seul octet
MAX_DELAY = 255  # le champ delai aussi
CMD_CUSTOM_PATCH = 0xFF


@dataclass
class Command:
    reg: int  # base $10/$20/$30 (sans le numero de voie), ou $FF
    data: int
    delay: int = 0  # en ticks 50 Hz
    patch: bytes | None = None  # seulement pour $FF


# --- Simplification ---------------------------------------------------------


def simplify(frames: list[Frame], cents: float = 0.0, vol_step: int = 1) -> list[Frame]:
    """Quantifie hauteur et volume pour que la deduplication morde davantage.

    cents    : grille de hauteur (0 = pas de quantification)
    vol_step : grille de volume, en crans de 3 dB
    """
    out: list[Frame] = []
    for f in frames:
        if not f.voiced:
            out.append(f)
            continue
        fnum, block = f.fnum, f.block
        if cents > 0:
            freq = fnum_block_to_freq(fnum, block)
            if freq > 0:
                # arrondi sur une grille logarithmique
                step = cents / 1200.0
                q = round(np.log2(freq) / step) * step
                fnum, block = freq_to_fnum_block(float(2.0**q))
        vol = f.volume
        if vol_step > 1:
            vol = int(min(15, round(vol / vol_step) * vol_step))
        out.append(Frame(True, fnum, block, vol, f.instrument, f.attack))
    return out


# --- Trames -> commandes ----------------------------------------------------


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
    """Simplifie progressivement jusqu'a tenir dans le budget de commandes.

    Retourne (commandes, frames_utilisees, info) ou info decrit le compromis
    applique — l'utilisateur doit savoir ce qui a ete sacrifie.

    quantize_pitch=False en mode melodique : la grille de quantification n'est
    pas alignee sur les demi-tons, elle desaccorderait les notes qu'on vient de
    caler. Les notes tenues compressent deja tres bien la hauteur, il ne reste
    que le volume a simplifier.
    """
    if quantize_pitch:
        ladder = [
            (0.0, 1), (15.0, 1), (25.0, 1), (25.0, 2), (40.0, 2),
            (60.0, 2), (60.0, 3), (100.0, 3), (150.0, 4), (200.0, 6),
        ]
    else:
        ladder = [(0.0, 1), (0.0, 2), (0.0, 3), (0.0, 4), (0.0, 6), (0.0, 8)]
    for cents, vstep in ladder:
        simple = simplify(frames, cents, vstep)
        cmds = frames_to_commands(simple, custom_patch, noise, channel,
                                  noise_pitch, noise_vol)
        if len(cmds) <= max_commands:
            info = {"cents": cents, "vol_step": vstep, "truncated": False}
            return cmds, simple, info

    # Dernier recours : on tronque, en le disant.
    cents, vstep = ladder[-1]
    simple = simplify(frames, cents, vstep)
    cmds = frames_to_commands(simple, custom_patch, noise, channel,
                              noise_pitch, noise_vol)[:max_commands]
    return cmds, simple, {"cents": cents, "vol_step": vstep, "truncated": True}


# --- Commandes -> evenements (pour le preview) ------------------------------


def commands_to_events(commands: list[Command], channel: int, rate: int = 44100,
                       tail_ticks: int = 12):
    """Rejoue exactement ce que le driver enverra a la puce.

    Le preview passe par la, et pas par les trames ideales : on veut entendre
    le resultat des commandes reellement generees, key-off final compris (le
    driver efface $20+voie quand le son se termine).
    """
    events = []
    t = 0  # en ticks 50 Hz
    spt = rate / 50.0  # echantillons par tick

    for cmd in commands:
        s = int(round(t * spt))
        if cmd.reg == CMD_CUSTOM_PATCH:
            patch = cmd.patch or b"\x00" * 8
            for reg in range(7, -1, -1):
                events.append((s, reg, patch[reg]))
            events.append((s, REG_INST_VOL + channel, 0x00))
        else:
            reg = cmd.reg + channel if cmd.reg > 0x0F else cmd.reg
            events.append((s, reg, cmd.data))
        t += cmd.delay

    events.append((int(round(t * spt)), REG_BLOCK + channel, 0x00))  # key-off du driver
    n = int(round((t + tail_ticks) * spt))
    return events, max(n, int(spt))


# --- Statistiques et sortie assembleur --------------------------------------


def stats(commands: list[Command]) -> dict:
    n = len(commands)
    ticks = sum(c.delay for c in commands)
    last_is_normal = bool(commands) and commands[-1].reg != CMD_CUSTOM_PATCH
    size = 2 + 3 * n - (1 if last_is_normal else 0)
    return {
        "commands": n,
        "bytes": size,
        "ticks": ticks,
        "seconds": ticks / 50.0,
        "over_budget": n > MAX_COMMANDS,
        "switches": sum(1 for c in commands if c.reg == REG_INST_VOL),
    }


def to_asm(
    name: str,
    channel: int,
    commands: list[Command],
    priority: int | None = None,
    source: str = "",
) -> str:
    """Bloc pret a coller dans objects/soundFX/soundFX.asm."""
    st = stats(commands)
    label = f"soundFX.{name}.data"
    patch_label = f"soundFX.{name}.patch"
    has_custom = any(c.reg == CMD_CUSTOM_PATCH for c in commands)

    out: list[str] = []
    out.append(f"; {name} - genere par to8-soundfx-generator")
    if source:
        out.append(f"; source : {source}")
    out.append(f"; {st['commands']} commandes, {st['bytes']} octets, "
               f"{st['seconds']:.2f} s, voie YM2413 {channel}")
    if priority is not None:
        out.append(f"; appel : _soundFX.play soundFX.{name},{priority}")
    if has_custom:
        out.append(";")
        out.append("; ATTENTION : ce son utilise l'instrument custom. Les registres")
        out.append("; $00-$07 sont GLOBAUX a la puce : si la musique s'en sert (c'est")
        out.append("; le cas de battlesquadron), son timbre sera casse.")

    if has_custom:
        patch = next(c.patch for c in commands if c.reg == CMD_CUSTOM_PATCH)
        out.append("")
        out.append(patch_label)
        out.append("        fcb     " + ",".join(f"${b:02X}" for b in patch))

    out.append("")
    out.append(label)
    out.append("        ; Header")
    out.append(f"        fcb     {st['commands']:<21d} ; nombre de commandes")
    out.append(f"        fcb     {channel:<21d} ; voie YM2413")
    out.append("")

    last = len(commands) - 1
    for i, c in enumerate(commands):
        if c.reg == CMD_CUSTOM_PATCH:
            out.append("        fcb     $FF")
            out.append(f"        fdb     {patch_label}   ; instrument custom")
            continue
        if i == last:
            out.append(f"        fcb     ${c.reg:02X},${c.data:02X}")
        else:
            out.append(f"        fcb     ${c.reg:02X},${c.data:02X},{c.delay}")
    return "\n".join(out) + "\n"
