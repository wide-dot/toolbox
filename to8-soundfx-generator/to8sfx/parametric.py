"""Mode parametrique : fabriquer un bruitage sans fichier source.

Pour un tir, une explosion ou un impact, l'analyse d'un .wav ne sert a rien :
ces sons sont domines par du bruit large bande, que la voie melodique du YM2413
ne sait pas produire. Ce que la puce sait faire, c'est un balayage de hauteur
avec une enveloppe — et c'est exactement ce que sont les donnees de r-type.

Le "jitter" fait sauter la hauteur d'une trame a l'autre : a forte dose, ca
imite grossierement du bruit, et c'est le meilleur substitut disponible pour
une explosion.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .analyze import FRAME_RATE
from .opll import Frame, freq_to_fnum_block


@dataclass
class SweepParams:
    duration_ms: int = 400
    f_start: float = 900.0
    f_end: float = 90.0
    pitch_curve: str = "exp"  # "exp" (log-lineaire, musical) ou "lin"
    vol_start: int = 0  # 0 = fort .. 15 = faible
    vol_end: int = 15
    vol_curve: str = "exp"
    instrument: int = 15
    jitter_cents: float = 0.0  # ecart aleatoire de hauteur par trame
    vibrato_hz: float = 0.0
    vibrato_cents: float = 0.0
    seed: int = 0

    def to_dict(self):
        return asdict(self)


def _interp(a: float, b: float, t: np.ndarray, curve: str) -> np.ndarray:
    if curve == "exp" and a > 0 and b > 0:
        return np.exp(np.log(a) + (np.log(b) - np.log(a)) * t)
    return a + (b - a) * t


def sweep(p: SweepParams) -> list[Frame]:
    n = max(1, int(round(p.duration_ms / 1000.0 * FRAME_RATE)))
    t = np.linspace(0.0, 1.0, n)
    rng = np.random.default_rng(p.seed)

    freq = _interp(max(p.f_start, 1e-3), max(p.f_end, 1e-3), t, p.pitch_curve)

    if p.vibrato_hz > 0 and p.vibrato_cents > 0:
        phase = 2 * np.pi * p.vibrato_hz * (np.arange(n) / FRAME_RATE)
        freq = freq * 2.0 ** (p.vibrato_cents / 1200.0 * np.sin(phase))

    if p.jitter_cents > 0:
        freq = freq * 2.0 ** (rng.normal(0.0, p.jitter_cents / 1200.0, n))

    vol = _interp(p.vol_start + 1.0, p.vol_end + 1.0, t, p.vol_curve) - 1.0
    vol = np.clip(np.round(vol), 0, 15).astype(int)

    frames: list[Frame] = []
    for i in range(n):
        f = float(np.clip(freq[i], 20.0, 8000.0))
        fnum, block = freq_to_fnum_block(f)
        frames.append(Frame(True, fnum, block, int(vol[i]), p.instrument))
    return frames


# Points de depart raisonnables, a retoucher a l'oreille dans l'interface.
PRESETS: dict[str, SweepParams] = {
    "laser": SweepParams(duration_ms=180, f_start=2400, f_end=300, pitch_curve="exp",
                         vol_start=2, vol_end=13, instrument=15),
    "tir-lourd": SweepParams(duration_ms=300, f_start=1200, f_end=120, pitch_curve="exp",
                             vol_start=0, vol_end=14, instrument=13),
    "explosion": SweepParams(duration_ms=560, f_start=520, f_end=45, pitch_curve="exp",
                             vol_start=0, vol_end=15, instrument=13,
                             jitter_cents=350.0),
    "impact": SweepParams(duration_ms=220, f_start=300, f_end=60, pitch_curve="exp",
                          vol_start=0, vol_end=15, instrument=14,
                          jitter_cents=200.0),
    "bonus": SweepParams(duration_ms=420, f_start=440, f_end=1760, pitch_curve="exp",
                         vol_start=3, vol_end=6, instrument=12),
    "power-up": SweepParams(duration_ms=600, f_start=220, f_end=2200, pitch_curve="exp",
                            vol_start=2, vol_end=8, instrument=10,
                            vibrato_hz=9.0, vibrato_cents=40.0),
    "alarme": SweepParams(duration_ms=800, f_start=700, f_end=700, pitch_curve="lin",
                          vol_start=2, vol_end=2, instrument=7,
                          vibrato_hz=6.0, vibrato_cents=500.0),
    "degat-joueur": SweepParams(duration_ms=900, f_start=180, f_end=40, pitch_curve="exp",
                                vol_start=1, vol_end=15, instrument=14,
                                jitter_cents=120.0),
}
