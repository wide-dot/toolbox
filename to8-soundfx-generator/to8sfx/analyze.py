"""Analyse d'un fichier audio : hauteur, enveloppe, voisement, a 50 Hz.

Le driver soundFX avance d'un tick par trame IRQ 50 Hz : toute l'analyse est
donc faite sur cette grille (un point tous les 20 ms). C'est la limite dure de
resolution temporelle du format, et c'est voulu qu'elle apparaisse ici.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

import numpy as np

from .opll import Frame, amplitude_to_volume, freq_to_fnum_block

FRAME_RATE = 50  # ticks par seconde (IRQ du jeu)
DEFAULT_RATE = 44100


# --- Chargement -------------------------------------------------------------


def load_audio(path: str, rate: int = DEFAULT_RATE) -> np.ndarray:
    """Charge n'importe quel format lisible par ffmpeg en mono float32."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg introuvable (necessaire pour lire wav/mp3)")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(rate),
         "-f", "f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg : {proc.stderr.decode(errors='replace')[:400]}")
    x = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)
    if x.size == 0:
        raise RuntimeError("fichier audio vide ou illisible")
    return x


# --- Detection de hauteur (YIN) ---------------------------------------------


def _yin_frame(seg: np.ndarray, rate: int, w: int, tau_min: int, tau_max: int,
               threshold: float):
    """Retourne (periode_en_echantillons, aperiodicite) pour un segment.

    seg doit contenir w + tau_max echantillons.
    """
    x = seg - seg.mean()
    a = x[:w]
    n = 1 << (len(x) + w).bit_length()
    corr = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(a, n)), n)[: tau_max + 1]

    cum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    taus = np.arange(tau_max + 1)
    r0 = cum[w]
    rt = cum[taus + w] - cum[taus]
    d = r0 + rt - 2.0 * corr

    # difference moyenne cumulee normalisee
    dp = np.ones_like(d)
    cs = np.cumsum(d[1:])
    dp[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cs, 1e-12)

    # seuil absolu : premier minimum local sous le seuil, sinon minimum global.
    # C'est ce qui protege des erreurs d'octave, contre lesquelles une simple
    # autocorrelation n'a aucune defense.
    tau = 0
    for t in range(tau_min, tau_max):
        if dp[t] < threshold:
            while t + 1 < tau_max and dp[t + 1] < dp[t]:
                t += 1
            tau = t
            break
    if tau == 0:
        tau = tau_min + int(np.argmin(dp[tau_min:tau_max]))

    # raffinement parabolique
    if 0 < tau < tau_max:
        a_, b_, c_ = d[tau - 1], d[tau], d[tau + 1]
        den = a_ - 2 * b_ + c_
        if den != 0:
            tau = tau + 0.5 * (a_ - c_) / den

    return float(tau), float(dp[int(round(tau))] if 0 < tau <= tau_max else 1.0)


@dataclass
class Analysis:
    rate: int
    audio: np.ndarray
    f0: np.ndarray  # Hz, 0 quand non voise
    rms: np.ndarray  # lineaire
    aperiodicity: np.ndarray  # 0 = parfaitement periodique
    voiced: np.ndarray  # bool
    warnings: list = field(default_factory=list)

    @property
    def n_frames(self) -> int:
        return len(self.f0)

    @property
    def duration(self) -> float:
        return self.n_frames / FRAME_RATE


def analyze(
    x: np.ndarray,
    rate: int = DEFAULT_RATE,
    fmin: float = 45.0,
    fmax: float = 5000.0,
    yin_threshold: float = 0.15,
    silence_db: float = -45.0,
) -> Analysis:
    hop = rate // FRAME_RATE
    w = 2048
    tau_min = max(2, int(rate / fmax))
    tau_max = min(w, int(rate / fmin))
    need = w + tau_max

    n_frames = max(1, int(np.ceil(len(x) / hop)))
    pad = np.concatenate([np.zeros(hop, dtype=np.float32), x,
                          np.zeros(need + hop, dtype=np.float32)])

    f0 = np.zeros(n_frames)
    aper = np.ones(n_frames)
    rms = np.zeros(n_frames)

    for i in range(n_frames):
        start = i * hop
        seg = pad[start : start + need].astype(np.float64)
        block = pad[start + hop // 2 : start + hop // 2 + hop]
        rms[i] = float(np.sqrt(np.mean(block**2))) if block.size else 0.0
        if rms[i] <= 0:
            continue
        tau, ap = _yin_frame(seg, rate, w, tau_min, tau_max, yin_threshold)
        aper[i] = ap
        if tau > 0:
            f0[i] = rate / tau

    peak = float(rms.max()) if rms.size else 0.0
    floor = peak * (10 ** (silence_db / 20.0))
    voiced = (aper < yin_threshold * 2.5) & (rms > floor) & (f0 > 0)
    f0 = np.where(voiced, f0, 0.0)

    a = Analysis(rate=rate, audio=x, f0=f0, rms=rms, aperiodicity=aper, voiced=voiced)

    # Le diagnostic honnete : un son majoritairement bruite ne peut pas etre
    # rendu par une voie melodique FM. Mieux vaut le dire tout de suite.
    ratio = float(voiced.mean()) if voiced.size else 0.0
    if ratio < 0.35:
        a.warnings.append(
            f"Son majoritairement bruite ({ratio*100:.0f} % de trames a hauteur "
            "detectable). La voie melodique du YM2413 ne sait pas faire de bruit : "
            "le rendu sera decevant. Pour une explosion ou un impact, le mode "
            "parametrique (balayage descendant + jitter) donnera un bien meilleur "
            "resultat."
        )
    if a.duration > 2.5:
        a.warnings.append(
            f"Duree {a.duration:.1f} s : le compteur de commandes de l'en-tete est "
            "sur un octet (255 maxi). Le son sera probablement tronque, decoupe "
            "ou trop compresse. Viser moins de 2 s."
        )
    return a


# --- Passage aux trames du driver -------------------------------------------


def _median_filter(v: np.ndarray, k: int) -> np.ndarray:
    if k < 3 or k % 2 == 0:
        return v
    pad = k // 2
    p = np.pad(v, pad, mode="edge")
    return np.array([np.median(p[i : i + k]) for i in range(len(v))])


def to_frames(
    a: Analysis,
    instrument: int = 1,
    smooth: int = 3,
    pitch_shift_semitones: float = 0.0,
    gain_db: float = 0.0,
) -> list[Frame]:
    """Analyse -> trames du driver (fnum/block/volume par tick 50 Hz)."""
    f0 = a.f0.copy()
    if smooth >= 3:
        # on ne lisse que les trames voisees, pour ne pas etaler la hauteur
        # sur les silences
        vf = f0.copy()
        vf[~a.voiced] = np.nan
        filled = np.where(np.isnan(vf), 0.0, vf)
        sm = _median_filter(filled, smooth)
        f0 = np.where(a.voiced, sm, 0.0)

    if pitch_shift_semitones:
        f0 = f0 * (2.0 ** (pitch_shift_semitones / 12.0))

    peak = float(a.rms.max()) if a.rms.size else 1.0
    gain = 10.0 ** (gain_db / 20.0)

    frames: list[Frame] = []
    for i in range(a.n_frames):
        if not a.voiced[i] or f0[i] <= 0:
            frames.append(Frame(False, 0, 0, 15, instrument))
            continue
        fnum, block = freq_to_fnum_block(float(f0[i]))
        vol = amplitude_to_volume(float(a.rms[i]) * gain, peak)
        frames.append(Frame(True, fnum, block, vol, instrument))
    return frames


def trim_bounds(frames: list[Frame]) -> tuple[int, int]:
    """Bornes [debut, fin[ du silence de tete et de queue."""
    first = next((i for i, f in enumerate(frames) if f.voiced), None)
    if first is None:
        return 0, 0
    last = max(i for i, f in enumerate(frames) if f.voiced)
    return first, last + 1


def trim_frames(frames: list[Frame]) -> list[Frame]:
    """Enleve le silence de tete et de queue (des octets gratuits en moins)."""
    a, b = trim_bounds(frames)
    return frames[a:b]


def slice_analysis(a: Analysis, audio: np.ndarray, start_ms: float | None,
                   end_ms: float | None) -> tuple[Analysis, np.ndarray]:
    """Restreint l'analyse et l'audio a une selection, sur la grille des trames.

    Les bornes sont arrondies au tick 50 Hz : c'est la vraie resolution du
    driver, autant que la selection le reflete.
    """
    hop = a.rate // FRAME_RATE
    n = a.n_frames
    i0 = 0 if start_ms is None else int(round(start_ms / 1000.0 * FRAME_RATE))
    i1 = n if end_ms is None else int(round(end_ms / 1000.0 * FRAME_RATE))
    i0 = max(0, min(n, i0))
    i1 = max(i0 + 1, min(n, i1))
    if i0 == 0 and i1 == n:
        return a, audio

    sub = Analysis(
        rate=a.rate,
        audio=audio[i0 * hop : i1 * hop],
        f0=a.f0[i0:i1],
        rms=a.rms[i0:i1],
        aperiodicity=a.aperiodicity[i0:i1],
        voiced=a.voiced[i0:i1],
        warnings=[w for w in a.warnings if "Duree" not in w],
    )
    if sub.duration > 2.5:
        sub.warnings.append(
            f"Selection de {sub.duration:.1f} s : le compteur de commandes de "
            "l'en-tete est sur un octet (255 maxi). Reduire la selection."
        )
    return sub, sub.audio
