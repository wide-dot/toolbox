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

from dataclasses import asdict, dataclass, fields

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
    # Pas de pitch_curve ici (contrairement a l'ancien mode parametrique) :
    # la hauteur est en demi-tons (midi0 + slide*t + 1/2*slide_delta*t**2),
    # donc deja sur une echelle logarithmique. Un choix exp/lin n'aurait pas
    # de sens : slide en demi-tons par trame ne veut rien dire sur une
    # interpolation lineaire en hertz.

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

# arp_steps n'est pas dans BOUNDS : c'est un tuple, pas un scalaire. Son
# domaine vit donc ici. Deux octaves de part et d'autre suffisent largement a
# un arpege de bruitage, et sans borne une chaine de mutations fait deriver les
# marches indefiniment — l'utilisateur en enchaine par dizaines.
ARP_STEP_MIN, ARP_STEP_MAX = -24, 24


def _envelope(p: SfxParams, n: int) -> np.ndarray:
    """Volume par trame, 0 = fort. Attaque depuis le silence, palier, chute."""
    vol = np.full(n, float(p.vol_end))
    i = 0
    if p.attack_frames > 0:
        k = min(p.attack_frames, n)
        # k + 1 points puis on jette le premier : la rampe ATTEINT le pic sur sa
        # derniere trame. Avec endpoint=False, une attaque d'une seule trame
        # rendait [15] -- silence franc -- et le son ne demarrait qu'a la trame
        # suivante. C'est le cas par defaut du dataclass.
        vol[:k] = np.linspace(15.0, float(p.vol_peak), k + 1)[1:]
        i = k
    if p.hold_frames > 0 and i < n:
        k = min(p.hold_frames, n - i)
        vol[i:i + k] = float(p.vol_peak)
        i += k
    if i < n:
        # meme raison : une chute d'une seule trame doit rejoindre vol_end,
        # pas rester au pic.
        vol[i:] = np.linspace(float(p.vol_peak), float(p.vol_end), n - i + 1)[1:]
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

    return frames, _noise_track(p, n)


def _noise_track(p: SfxParams, n: int) -> list[int] | None:
    """Rafale de frappes, dont la densite s'accelere ou retombe.

    Les instants sont tires sur une courbe de puissance u**gamma : un exposant
    superieur a 1 (courbe convexe) tasse les frappes au debut, la ou u varie
    peu pour un grand pas de position (la densite retombe : une explosion) ;
    un exposant inferieur a 1 (concave) les tasse a la fin (elle accelere).
    Un accel negatif doit donc donner un gamma SUPERIEUR a 1 : le signe est
    inverse par rapport a accel, d'ou le moins dans l'exposant ci-dessous.
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


# --- Categories -------------------------------------------------------------
#
# Une categorie est un a priori sur l'espace des parametres : quelles couches
# sont actives, et dans quelles plages tirer. Ce sont des EVENEMENTS DE JEU, pas
# des familles de synthese — c'est ce qui rend le tirage utile : on cherche
# "une explosion", pas "un balayage descendant avec du jitter".
#
# `ranges` remplace la borne globale de BOUNDS pendant le tirage ; `fixed` force
# une valeur. Ce qui n'est cite ni dans l'un ni dans l'autre garde le defaut.
#
# AUCUNE categorie ne touche noise_on. La couche bruit bascule la puce en mode
# rythme, ce qui requisitionne ses voies 6 a 8 : si la musique du jeu s'en sert,
# son etat de batterie est ecrase. Une machine ne doit pas decider ca a la place
# de l'auteur du jeu, meme pour une explosion. Les categories decrivent en
# revanche le kit et la forme de rafale qui conviendraient, pour que la couche
# sonne juste le jour ou l'utilisateur l'active lui-meme.

CATEGORIES: dict[str, dict] = {
    "tir": {
        "label": "Tir",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (3, 10), "f_start": (1200, 4000),
                   "slide": (-2.5, -0.8), "slide_delta": (0.0, 0.06),
                   "instrument": (12, 15), "jitter_cents": (0, 60)},
        "fixed": {"vol_peak": 1, "vol_end": 14},
    },
    "explosion": {
        "label": "Explosion",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 3),
                   "decay_frames": (15, 45), "f_start": (200, 700),
                   "slide": (-0.6, -0.1), "jitter_cents": (250, 900),
                   "instrument": (13, 14), "noise_hits": (10, 30),
                   "noise_spread_frames": (12, 45), "noise_accel": (-1.0, -0.4),
                   "noise_pitch": (0, 5), "noise_vol": (0, 5)},
        "fixed": {"vol_peak": 0, "vol_end": 15,
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
        "fixed": {"vol_peak": 0, "vol_end": 15,
                  "noise_kit": ("BD", "TOM")},
    },
    "ramassage": {
        "label": "Ramassage",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (1, 4),
                   "decay_frames": (4, 12), "f_start": (500, 1400),
                   "slide": (0.0, 0.8), "arp_frames": (1, 3),
                   "instrument": (10, 12)},
        "fixed": {"vol_peak": 2, "vol_end": 12,
                  "arp_steps": (0, 4, 7, 12), "arp_retrigger": True},
    },
    "saut": {
        "label": "Saut",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (5, 14), "f_start": (200, 600),
                   "slide": (0.6, 2.2), "slide_delta": (-0.08, 0.0),
                   "instrument": (10, 15)},
        "fixed": {"vol_peak": 2, "vol_end": 13},
    },
    "degat": {
        "label": "Degat",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (0, 2),
                   "decay_frames": (15, 40), "f_start": (90, 300),
                   "slide": (-0.8, -0.2), "jitter_cents": (60, 250),
                   "instrument": (13, 14)},
        "fixed": {"vol_peak": 1, "vol_end": 15},
    },
    "menu": {
        "label": "Menu",
        "ranges": {"attack_frames": (0, 1), "hold_frames": (1, 3),
                   "decay_frames": (2, 6), "f_start": (700, 2200),
                   "slide": (-0.3, 0.3), "instrument": (10, 12)},
        "fixed": {"vol_peak": 3, "vol_end": 12},
    },
    "alarme": {
        "label": "Alarme",
        "ranges": {"attack_frames": (0, 2), "hold_frames": (10, 30),
                   "decay_frames": (2, 8), "f_start": (400, 1100),
                   "slide": (-0.05, 0.05), "vibrato_hz": (4, 12),
                   "vibrato_cents": (300, 900), "repeat_frames": (0, 20),
                   "instrument": (5, 8)},
        "fixed": {"vol_peak": 2, "vol_end": 4},
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
        out.arp_steps = tuple(
            int(max(ARP_STEP_MIN, min(ARP_STEP_MAX, s + rng.integers(-2, 3))))
            for s in p.arp_steps)
    return out
