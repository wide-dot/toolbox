"""Acces a la puce YM2413 (OPLL) : emulation, patchs ROM, conversions.

L'emulation vient d'emu2413 (Mitsutaka Okazaki, MIT), compile en lib native par
build.sh et pilote via ctypes. Un rendu = un seul appel natif.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from dataclasses import dataclass

import numpy as np

# --- Materiel ---------------------------------------------------------------

# Horloge annoncee dans l'en-tete de engine/sound/soundFX.asm.
YM2413_CLOCK = 3579545

# Registres (bases ; le driver ajoute le numero de voie aux registres > $0F)
REG_CUSTOM_PATCH = 0x00  # $00-$07, patch custom GLOBAL a la puce
REG_RHYTHM = 0x0E
REG_FNUM_LO = 0x10  # $10+voie : F-Number, 8 bits de poids faible
REG_BLOCK = 0x20  # $20+voie : bit0 F-Num b8, b1-3 block, b4 key-on, b5 sustain
REG_INST_VOL = 0x30  # $30+voie : b4-7 instrument, b0-3 volume (0 = fort)

KEY_ON = 0x10
SUSTAIN = 0x20

# Noms des 15 instruments ROM du YM2413 (l'instrument 0 est le patch custom).
INSTRUMENTS = {
    0: "Custom",
    1: "Violin",
    2: "Guitar",
    3: "Piano",
    4: "Flute",
    5: "Clarinet",
    6: "Oboe",
    7: "Trumpet",
    8: "Organ",
    9: "Horn",
    10: "Synthesizer",
    11: "Harpsichord",
    12: "Vibraphone",
    13: "Synthesizer Bass",
    14: "Acoustic Bass",
    15: "Electric Guitar",
}
ROM_INSTRUMENTS = [i for i in range(1, 16)]

# Le volume est sur 4 bits, 0 = le plus fort, chaque cran attenue de 3 dB.
DB_PER_VOLUME_STEP = 3.0
VOLUME_MAX = 15


# --- Lib native -------------------------------------------------------------

_LIB = None
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lib_path() -> str:
    ext = "dylib" if platform.system() == "Darwin" else "so"
    return os.path.join(_ROOT, "build", f"libto8opll.{ext}")


def load_library(auto_build: bool = True):
    """Charge (et compile au besoin) la lib native."""
    global _LIB
    if _LIB is not None:
        return _LIB

    path = _lib_path()
    if not os.path.exists(path) and auto_build:
        subprocess.run([os.path.join(_ROOT, "build.sh")], check=True)
    if not os.path.exists(path):
        raise RuntimeError(f"lib native absente : {path}\nLancer ./build.sh")

    lib = ctypes.CDLL(path)
    lib.opll_render.restype = ctypes.c_int
    lib.opll_render.argtypes = [
        ctypes.c_uint32,  # clk
        ctypes.c_uint32,  # rate
        ctypes.c_int,  # chip_type
        ctypes.POINTER(ctypes.c_uint32),  # ev_t
        ctypes.POINTER(ctypes.c_uint8),  # ev_r
        ctypes.POINTER(ctypes.c_uint8),  # ev_v
        ctypes.c_int,  # nev
        ctypes.POINTER(ctypes.c_int16),  # out
        ctypes.c_int,  # nsamples
    ]
    lib.opll_default_patch_dump.restype = None
    lib.opll_default_patch_dump.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint8),
    ]
    _LIB = lib
    return lib


def render(events, nsamples: int, rate: int = 44100) -> np.ndarray:
    """Rend un flux d'ecritures registres.

    events : iterable de (instant_en_echantillons, registre, valeur)
    Retourne un float32 mono dans [-1, 1].
    """
    lib = load_library()
    events = sorted(events, key=lambda e: e[0])
    nev = len(events)

    if nev:
        et = np.ascontiguousarray([e[0] for e in events], dtype=np.uint32)
        er = np.ascontiguousarray([e[1] & 0xFF for e in events], dtype=np.uint8)
        ev = np.ascontiguousarray([e[2] & 0xFF for e in events], dtype=np.uint8)
    else:
        et = np.zeros(0, dtype=np.uint32)
        er = np.zeros(0, dtype=np.uint8)
        ev = np.zeros(0, dtype=np.uint8)

    out = np.zeros(max(1, nsamples), dtype=np.int16)
    lib.opll_render(
        YM2413_CLOCK,
        rate,
        0,  # OPLL_2413_TONE
        et.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),
        er.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        ev.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        nev,
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
        nsamples,
    )
    return out[:nsamples].astype(np.float32) / 32768.0


def rom_patch_dump(num: int) -> bytes:
    """Les 8 octets du patch ROM `num` (1..15), au format de la commande $FF."""
    lib = load_library()
    buf = (ctypes.c_uint8 * 8)()
    lib.opll_default_patch_dump(0, int(num), buf)
    return bytes(buf)


# --- Conversions hauteur / volume -------------------------------------------
#
# La frequence de sortie du YM2413 vaut :
#     f = fnum * clk / 72 / 2**(19 - block)
# La constante est verifiee par mesure sur l'emulateur (voir tests/test_opll.py),
# on ne se fie pas a la documentation seule.

FNUM_MAX = 511
BLOCK_MAX = 7


def fnum_block_to_freq(fnum: int, block: int) -> float:
    return fnum * YM2413_CLOCK / 72.0 / (2.0 ** (19 - block))


def freq_to_fnum_block(freq: float, prefer_block: int | None = None):
    """Meilleur couple (fnum, block) pour une frequence en Hz.

    On prend le block le plus bas qui garde fnum <= 511 : c'est celui qui donne
    la meilleure resolution en hauteur.
    """
    if freq <= 0:
        return 0, 0
    for block in range(0, BLOCK_MAX + 1):
        if prefer_block is not None and block < prefer_block:
            continue
        fnum = int(round(freq * 72.0 * (2.0 ** (19 - block)) / YM2413_CLOCK))
        if fnum <= FNUM_MAX:
            return max(0, min(FNUM_MAX, fnum)), block
    return FNUM_MAX, BLOCK_MAX


def amplitude_to_volume(amp: float, peak: float) -> int:
    """Amplitude lineaire -> volume 4 bits (0 = fort, 15 = faible)."""
    if amp <= 0 or peak <= 0:
        return VOLUME_MAX
    db = 20.0 * np.log10(max(amp / peak, 1e-6))
    return int(np.clip(round(-db / DB_PER_VOLUME_STEP), 0, VOLUME_MAX))


@dataclass
class Frame:
    """Un tick 50 Hz du bruitage."""

    voiced: bool
    fnum: int
    block: int
    volume: int  # 0 = fort .. 15 = faible
    instrument: int  # 0 = custom, 1..15 = ROM
    attack: bool = False  # relancer l'enveloppe (debut de note)


# --- Notes ------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
A4_MIDI = 69
A4_FREQ = 440.0


def freq_to_midi(freq: float, tuning_cents: float = 0.0) -> float:
    """Hauteur en demi-tons MIDI (69 = la 440). Valeur continue."""
    if freq <= 0:
        return 0.0
    return A4_MIDI + 12.0 * np.log2(freq / A4_FREQ) - tuning_cents / 100.0


def midi_to_freq(midi: float, tuning_cents: float = 0.0) -> float:
    return A4_FREQ * 2.0 ** ((midi - A4_MIDI + tuning_cents / 100.0) / 12.0)


def midi_name(midi: int) -> str:
    return f"{NOTE_NAMES[int(midi) % 12]}{int(midi) // 12 - 1}"
