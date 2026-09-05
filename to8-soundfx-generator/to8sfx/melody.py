"""Mode melodique : caler la hauteur sur des notes tenues.

Sur un jingle de bonus ou un power-up, la courbe de hauteur brute ondule —
vibrato, portamento, et les hesitations du detecteur. Snapper chaque trame au
demi-ton le plus proche ne suffit pas : quand la hauteur passe pres d'une
frontiere, la note papillonne entre deux demi-tons d'une trame a l'autre.

On decoupe donc en NOTES : on regroupe les trames en segments stables, on prend
la mediane de chaque segment, et on tient cette note du debut a la fin. Effet de
bord tres appreciable — une note tenue devient une seule commande avec un long
delai au lieu d'une par trame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .opll import (
    Frame,
    fnum_block_to_freq,
    freq_to_fnum_block,
    freq_to_midi,
    midi_name,
    midi_to_freq,
)

# Intervalles en demi-tons depuis la tonique.
SCALES: dict[str, list[int]] = {
    "chromatique": list(range(12)),
    "majeure": [0, 2, 4, 5, 7, 9, 11],
    "mineure": [0, 2, 3, 5, 7, 8, 10],
    "penta-majeure": [0, 2, 4, 7, 9],
    "penta-mineure": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
}


@dataclass
class Note:
    start: int  # premiere trame
    end: int  # derniere trame + 1
    midi: int
    name: str
    freq: float

    @property
    def frames(self) -> int:
        return self.end - self.start

    def to_dict(self):
        return {"start": self.start, "end": self.end, "midi": self.midi,
                "name": self.name, "freq": round(self.freq, 2),
                "ms": round(self.frames * 20)}


def frame_freqs(frames: list[Frame]) -> np.ndarray:
    return np.array([fnum_block_to_freq(f.fnum, f.block) if f.voiced else 0.0
                     for f in frames])


def _runs(midi_f: np.ndarray, voiced: np.ndarray, min_note_frames: int):
    """Decoupe la suite de hauteurs en segments [debut, fin, demi-ton]."""
    snapped = np.where(voiced, np.round(midi_f), 0).astype(int)
    if voiced.any():
        snapped = np.where(voiced, _median_int(snapped, max(3, min_note_frames)), 0)

    runs: list[list[int]] = []
    for i in range(len(midi_f)):
        if not voiced[i]:
            runs.append([i, i + 1, 0])
        elif runs and runs[-1][2] == snapped[i] and runs[-1][2] != 0:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1, int(snapped[i])])

    # Absorber les segments trop courts dans un voisin ASSEZ LONG.
    #
    # La condition sur le voisin est essentielle : sans elle, une suite de
    # segments tous courts — c'est exactement ce qu'est un glissando — se
    # mange de proche en proche et finit en une seule note, la mediane de tout
    # le balayage. On ne nettoie donc que les papillonnements en bord d'une
    # vraie note tenue ; quand aucun voisin n'est stable, on laisse la suite de
    # notes courtes telle quelle, ce qui donne un glissando arpege.
    def _long(r):
        return r[2] != 0 and (r[1] - r[0]) >= min_note_frames

    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[2] == 0 or (r[1] - r[0]) >= min_note_frames:
                continue
            cands = [runs[j] for j in (i - 1, i + 1)
                     if 0 <= j < len(runs) and _long(runs[j])]
            if not cands:
                continue
            target = max(cands, key=lambda x: x[1] - x[0])
            target[0], target[1] = min(target[0], r[0]), max(target[1], r[1])
            runs.pop(i)
            changed = True
            break
    return runs


def estimate_tuning(frames: list[Frame], min_note_frames: int = 3,
                    with_confidence: bool = False):
    """Desaccord global de la source, en cents.

    Un enregistrement tombe rarement pile sur le la 440 : on mesure l'ecart au
    demi-ton le plus proche et on le compense, sinon toutes les notes sont
    snappees du mauvais cote pres des frontieres.

    Deux pieges se combinent ici, et il faut les traiter separement :

    - le **vibrato** fait osciller l'ecart autour de sa vraie valeur. Une
      moyenne s'y laisse biaiser des que l'oscillation ne couvre pas un nombre
      entier de cycles ; une mediane, non.
    - l'ecart est une grandeur **circulaire** dans [-50, +50] cents : au-dela
      il s'enroule. Une mediane y est fausse des que la source est desaccordee
      de plus de quelques dizaines de cents ; une moyenne circulaire, non.

    D'ou : mediane a l'interieur de chaque note (contre le vibrato), puis
    moyenne circulaire entre les notes, ponderee par leur duree (contre
    l'enroulement).

    with_confidence=True renvoie (cents, confiance). La confiance est la
    longueur du vecteur resultant de la moyenne circulaire, dans [0, 1] : elle
    tombe quand les notes ne s'accordent pas sur un meme desaccord, ce qui
    arrive des que le vibrato depasse le demi-ton ou que la source est pile
    entre deux demi-tons. Dans ces cas-la aucun estimateur ne peut trancher, et
    mieux vaut le dire que compenser au hasard.
    """
    fail = (0.0, 0.0) if with_confidence else 0.0
    midi_f = np.array([freq_to_midi(float(f)) if f > 0 else 0.0
                       for f in frame_freqs(frames)])
    voiced = np.array([f.voiced for f in frames])
    if voiced.sum() < 3:
        return fail

    devs, weights = [], []
    for start, end, val in _runs(midi_f, voiced, min_note_frames):
        if val == 0:
            continue
        seg = midi_f[start:end]
        seg = seg[seg > 0]
        if seg.size == 0:
            continue
        med = float(np.median(seg))
        devs.append(med - round(med))
        weights.append(seg.size)
    if not devs:
        return fail

    ang = 2.0 * np.pi * np.array(devs)  # un tour = un demi-ton
    w = np.array(weights, dtype=float)
    c = float((w * np.cos(ang)).sum() / w.sum())
    s = float((w * np.sin(ang)).sum() / w.sum())
    conf = float(np.hypot(c, s))
    if conf < 0.05:
        return fail  # aucune direction dominante : ne rien compenser
    cents = float(np.arctan2(s, c) / (2.0 * np.pi) * 100.0)
    return (cents, conf) if with_confidence else cents


def _snap_to_scale(midi: int, scale: str, root: int) -> int:
    degrees = SCALES.get(scale) or SCALES["chromatique"]
    if len(degrees) == 12:
        return midi
    best, bestd = midi, 99
    for octave in (-1, 0, 1):
        for d in degrees:
            cand = (midi // 12 + octave) * 12 + ((root + d) % 12)
            dist = abs(cand - midi)
            if dist < bestd:
                best, bestd = cand, dist
    return best


def _median_int(v: np.ndarray, k: int) -> np.ndarray:
    if k < 3:
        return v
    if k % 2 == 0:
        k += 1
    pad = k // 2
    p = np.pad(v, pad, mode="edge")
    return np.array([int(np.median(p[i : i + k])) for i in range(len(v))])


def quantize(
    frames: list[Frame],
    tuning_cents: float | None = None,
    min_note_frames: int = 3,
    scale: str = "chromatique",
    root: int = 0,
    retrigger: bool = True,
) -> tuple[list[Frame], list[Note], float, float]:
    """Cale les trames sur des notes tenues.

    tuning_cents=None : mesure le desaccord de la source et le compense.
    Retourne (trames, notes, desaccord_utilise, confiance_du_desaccord).
    """
    if not frames:
        return frames, [], 0.0, 0.0

    # Passe 1 : mesurer le desaccord (elle fait son propre decoupage).
    # Passe 2 : redecouper avec la hauteur compensee.
    if tuning_cents is None:
        tuning, confidence = estimate_tuning(frames, min_note_frames, True)
    else:
        tuning, confidence = float(tuning_cents), 1.0
    freqs = frame_freqs(frames)
    voiced = np.array([f.voiced for f in frames])
    midi_f = np.array([freq_to_midi(float(f), tuning) if f > 0 else 0.0 for f in freqs])
    runs = _runs(midi_f, voiced, min_note_frames)

    # note definitive = mediane des hauteurs continues du segment
    out = [Frame(f.voiced, f.fnum, f.block, f.volume, f.instrument, False) for f in frames]
    notes: list[Note] = []
    for start, end, val in runs:
        if val == 0:
            continue
        seg = midi_f[start:end]
        seg = seg[seg > 0]
        if seg.size == 0:
            continue
        midi = int(round(float(np.median(seg))))
        midi = _snap_to_scale(midi, scale, root)
        freq = midi_to_freq(midi, tuning)
        fnum, block = freq_to_fnum_block(freq)
        for i in range(start, end):
            out[i].fnum, out[i].block = fnum, block
        if retrigger:
            out[start].attack = True
        notes.append(Note(start, end, midi, midi_name(midi), freq))

    return out, notes, tuning, confidence


def describe(notes: list[Note]) -> str:
    return " ".join(f"{n.name}({n.frames * 20}ms)" for n in notes)
