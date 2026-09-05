"""Choix de l'instrument : appariement spectral et entrelacement.

Le numero d'instrument est le quartet haut de $30+voie. L'ecrire ne relance PAS
la note (le key-on est dans $20), on peut donc changer de patch en cours de son
pour 3 octets. Entrelacer deux patchs peut donner un timbre hybride... ou de la
bouillie : le changement modifie les operateurs sous une enveloppe deja lancee.
C'est au preview de trancher, pas a la theorie.
"""

from __future__ import annotations

import numpy as np

from . import opll
from .analyze import FRAME_RATE
from .opll import Frame

N_BANDS = 24
FMIN_BAND = 100.0
FMAX_BAND = 8000.0
N_FFT = 1024


def render_frames(frames: list[Frame], channel: int = 0, rate: int = 44100,
                  tail_ticks: int = 8) -> np.ndarray:
    """Rendu direct des trames (sans deduplication), aligne au tick pres.

    Utilise pour l'appariement : on veut une correspondance exacte trame a
    trame avec la source. Le preview, lui, passe par les commandes reellement
    generees (codegen.commands_to_events).
    """
    spt = rate / FRAME_RATE
    events = []
    prev = {}
    for i, f in enumerate(frames):
        s = int(round(i * spt))
        if f.voiced:
            rb = opll.REG_BLOCK + channel
            if f.attack and (prev.get(rb, 0) & opll.KEY_ON):
                off = prev[rb] & ~opll.KEY_ON
                events.append((s, rb, off))
                prev[rb] = off
            want = {
                opll.REG_INST_VOL + channel: (f.instrument << 4) | (f.volume & 0x0F),
                opll.REG_FNUM_LO + channel: f.fnum & 0xFF,
                opll.REG_BLOCK + channel: ((f.fnum >> 8) & 1) | ((f.block & 7) << 1) | opll.KEY_ON,
            }
        else:
            want = {opll.REG_BLOCK + channel: (prev.get(opll.REG_BLOCK + channel, 0)) & ~opll.KEY_ON}
        for reg in (opll.REG_INST_VOL + channel, opll.REG_FNUM_LO + channel,
                    opll.REG_BLOCK + channel):
            if reg in want and prev.get(reg) != want[reg]:
                events.append((s, reg, want[reg]))
                prev[reg] = want[reg]
    n = int(round((len(frames) + tail_ticks) * spt))
    events.append((int(round(len(frames) * spt)), opll.REG_BLOCK + channel, 0))
    return opll.render(events, max(n, int(spt)), rate)


def _filterbank(rate: int, n_fft: int) -> np.ndarray:
    freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
    edges = np.geomspace(FMIN_BAND, min(FMAX_BAND, rate / 2 * 0.98), N_BANDS + 2)
    fb = np.zeros((N_BANDS, len(freqs)))
    for b in range(N_BANDS):
        lo, mid, hi = edges[b], edges[b + 1], edges[b + 2]
        left = (freqs >= lo) & (freqs <= mid)
        right = (freqs > mid) & (freqs <= hi)
        fb[b, left] = (freqs[left] - lo) / max(mid - lo, 1e-9)
        fb[b, right] = (hi - freqs[right]) / max(hi - mid, 1e-9)
    return fb


def spectral_features(x: np.ndarray, rate: int, n_frames: int) -> np.ndarray:
    """Vecteur de timbre par trame : energies de bandes log, normalisees.

    On normalise chaque trame pour comparer la FORME du spectre et pas le
    niveau : le volume est deja gere separement par le registre $30.
    """
    hop = rate // FRAME_RATE
    fb = _filterbank(rate, N_FFT)
    win = np.hanning(N_FFT)
    pad = np.concatenate([np.zeros(N_FFT // 2), x, np.zeros(N_FFT + hop * 2)])
    feats = np.zeros((n_frames, N_BANDS))
    for i in range(n_frames):
        seg = pad[i * hop : i * hop + N_FFT]
        if len(seg) < N_FFT:
            seg = np.pad(seg, (0, N_FFT - len(seg)))
        mag = np.abs(np.fft.rfft(seg * win))
        band = fb @ mag
        band = np.log10(band + 1e-8)
        band = band - band.mean()
        norm = np.linalg.norm(band)
        feats[i] = band / norm if norm > 1e-9 else band
    return feats


def cost_matrix(source: np.ndarray, frames: list[Frame], rate: int = 44100,
                channel: int = 0, candidates: list[int] | None = None):
    """Distance timbre source <-> rendu, pour chaque instrument et chaque trame."""
    candidates = candidates or opll.ROM_INSTRUMENTS
    n = len(frames)
    src = spectral_features(source, rate, n)

    weight = np.array([0.0 if not f.voiced else 10 ** (-f.volume * 3.0 / 20.0)
                       for f in frames])
    if weight.sum() <= 0:
        weight = np.ones(n)

    cost = np.zeros((len(candidates), n))
    for k, inst in enumerate(candidates):
        variant = [Frame(f.voiced, f.fnum, f.block, f.volume, inst, f.attack) for f in frames]
        y = render_frames(variant, channel, rate)
        feats = spectral_features(y, rate, n)
        cost[k] = np.linalg.norm(feats - src, axis=1) * weight
    return cost, candidates


def rank_instruments(cost: np.ndarray, candidates: list[int]):
    """Classement des instruments, du plus proche au plus eloigne."""
    totals = cost.sum(axis=1)
    order = np.argsort(totals)
    best = totals[order[0]] if len(order) else 1.0
    return [
        {
            "instrument": candidates[i],
            "name": opll.INSTRUMENTS[candidates[i]],
            "cost": float(totals[i]),
            "relative": float(totals[i] / best) if best > 0 else 1.0,
        }
        for i in order
    ]


def interleave(cost: np.ndarray, candidates: list[int], switch_penalty: float = 0.8):
    """Viterbi : suite d'instruments par trame, avec penalite par bascule.

    Chaque bascule coute 3 octets dans les donnees ; la penalite empeche
    l'optimiseur de partir en 50 changements par seconde pour grappiller trois
    millimes de distance spectrale.
    """
    k, n = cost.shape
    if n == 0:
        return []
    dp = np.zeros((k, n))
    back = np.zeros((k, n), dtype=int)
    dp[:, 0] = cost[:, 0]
    for t in range(1, n):
        prev = dp[:, t - 1]
        stay = prev
        best_other = np.full(k, np.inf)
        order = np.argsort(prev)
        b0, b1 = order[0], (order[1] if k > 1 else order[0])
        for i in range(k):
            src = b1 if i == b0 else b0
            best_other[i] = prev[src] + switch_penalty
            if stay[i] <= best_other[i]:
                dp[i, t] = stay[i] + cost[i, t]
                back[i, t] = i
            else:
                dp[i, t] = best_other[i] + cost[i, t]
                back[i, t] = src
    path = [int(np.argmin(dp[:, -1]))]
    for t in range(n - 1, 0, -1):
        path.append(int(back[path[-1], t]))
    path.reverse()
    return [candidates[i] for i in path]


def apply_instruments(frames: list[Frame], per_frame: list[int]) -> list[Frame]:
    return [Frame(f.voiced, f.fnum, f.block, f.volume, per_frame[i], f.attack)
            for i, f in enumerate(frames)]


# --- Ajustement du patch custom ---------------------------------------------


def fit_custom_patch(source: np.ndarray, frames: list[Frame], rate: int = 44100,
                     channel: int = 0, seed_instrument: int = 1,
                     iterations: int = 220, rng_seed: int = 0):
    """Cherche 8 octets de patch qui rapprochent le rendu de la source.

    Descente locale a partir d'un patch ROM : le format est trop contraint et
    trop non-lineaire pour un ajustement analytique, mais l'espace est petit et
    quelques centaines d'essais suffisent a faire nettement mieux qu'un patch
    ROM pris tel quel.
    """
    rng = np.random.default_rng(rng_seed)
    n = len(frames)
    src = spectral_features(source, rate, n)
    weight = np.array([0.0 if not f.voiced else 10 ** (-f.volume * 3.0 / 20.0)
                       for f in frames])
    if weight.sum() <= 0:
        weight = np.ones(n)

    def score(patch: bytes) -> float:
        variant = [Frame(f.voiced, f.fnum, f.block, f.volume, 0, f.attack) for f in frames]
        ev, _ = _patch_events(variant, patch, channel, rate)
        y = opll.render(ev, int((n + 8) * rate / FRAME_RATE), rate)
        return float((np.linalg.norm(spectral_features(y, rate, n) - src, axis=1)
                      * weight).sum())

    best = bytearray(opll.rom_patch_dump(seed_instrument))
    best_score = score(bytes(best))
    for _ in range(iterations):
        cand = bytearray(best)
        for _ in range(int(rng.integers(1, 3))):
            i = int(rng.integers(0, 8))
            delta = int(rng.integers(-3, 4)) * (1 << int(rng.integers(0, 5)))
            cand[i] = max(0, min(255, cand[i] + delta))
        s = score(bytes(cand))
        if s < best_score:
            best, best_score = cand, s
    return bytes(best), best_score


def _patch_events(frames: list[Frame], patch: bytes, channel: int, rate: int):
    spt = rate / FRAME_RATE
    events = [(0, reg, patch[reg]) for reg in range(7, -1, -1)]
    prev = {}
    for i, f in enumerate(frames):
        s = int(round(i * spt))
        if f.voiced:
            want = {
                opll.REG_INST_VOL + channel: (0 << 4) | (f.volume & 0x0F),
                opll.REG_FNUM_LO + channel: f.fnum & 0xFF,
                opll.REG_BLOCK + channel: ((f.fnum >> 8) & 1) | ((f.block & 7) << 1) | opll.KEY_ON,
            }
        else:
            want = {opll.REG_BLOCK + channel: prev.get(opll.REG_BLOCK + channel, 0) & ~opll.KEY_ON}
        for reg in (opll.REG_INST_VOL + channel, opll.REG_FNUM_LO + channel,
                    opll.REG_BLOCK + channel):
            if reg in want and prev.get(reg) != want[reg]:
                events.append((s, reg, want[reg]))
                prev[reg] = want[reg]
    return events, len(frames)
