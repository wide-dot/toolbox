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
    DB_PER_VOLUME_STEP,
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


def _onsets(level_db: np.ndarray, voiced: np.ndarray,
            threshold_db: float = 1.5, min_gap: int = 1) -> set[int]:
    """Trames ou l'enveloppe repart : un debut de note.

    C'est la seule information qui separe deux notes de MEME hauteur — la
    hauteur, elle, ne distingue pas quatre doubles croches sur D5 d'un D5
    tenu — et la seule qui distingue une vraie note breve d'une hesitation du
    detecteur.

    Un debut de note est une remontee franche du niveau. On exige un maximum
    local de la montee, pour ne pas declencher deux fois sur la meme attaque.
    L'ecart minimal entre deux attaques est d'UNE trame : le driver ne sait de
    toute facon rien representer de plus rapide, et l'interdire plafonnerait le
    debit de notes a une toutes les deux trames. threshold_db <= 0 desactive.
    """
    n = len(level_db)
    if n == 0 or threshold_db <= 0:
        return set()
    rise = np.zeros(n)
    rise[1:] = np.maximum(0.0, np.diff(level_db))

    out: set[int] = set()
    last = -(10**6)
    for i in range(n):
        if not voiced[i]:
            continue
        if i == 0 or not voiced[i - 1]:
            start = True  # sortie de silence
        else:
            start = (rise[i] >= threshold_db
                     and rise[i] >= rise[i - 1]
                     and (i + 1 >= n or rise[i] >= rise[i + 1]))
        if start and i - last >= min_gap:
            out.add(i)
            last = i
    return out


def frame_levels(frames: list[Frame]) -> np.ndarray:
    """Enveloppe de repli, deduite du volume des trames (3 dB par cran).

    Moins fine que le RMS de la source — 3 dB de resolution — mais suffisante
    pour les attaques, et disponible meme quand la source n'est pas un fichier
    audio (mode parametrique, relecture d'un son existant).
    """
    return np.array([-3.0 * f.volume for f in frames])


def _runs(midi_f: np.ndarray, voiced: np.ndarray, min_note_frames: int,
          onsets: set[int] | None = None):
    """Decoupe la suite de hauteurs en segments [debut, fin, demi-ton].

    Deux sources de frontieres : le changement de hauteur, et l'attaque
    d'enveloppe. La seconde est indispensable — sans elle une note repetee est
    indistinguable d'une note tenue, et tout un trait rapide se fait avaler par
    le nettoyage ci-dessous.
    """
    onsets = onsets or set()

    # Filtre median de largeur 3, et 3 seulement : il est la pour tuer les
    # erreurs d'une trame du detecteur. L'elargir avec min_note_frames — ce
    # qu'on faisait — efface purement et simplement les notes plus courtes que
    # sa demi-largeur, avant meme qu'on ait pu les compter.
    #
    # A min_note_frames = 1 il est desactive : l'utilisateur declare alors que
    # la note la plus breve dure une trame, et un filtre de largeur 3 ne peut
    # pas la laisser passer. On garde alors chaque trame telle quelle, erreurs
    # du detecteur comprises — c'est le prix a payer, et c'est un choix.
    snapped = np.where(voiced, np.round(midi_f), 0).astype(int)
    if voiced.any() and min_note_frames >= 2:
        # ... et il ne doit pas traverser une attaque. Sur un trait a une note
        # par trame, un filtre glissant de largeur 3 melange trois notes
        # differentes et rend une alternance qui n'a jamais ete jouee. On
        # filtre donc a l'interieur de chaque cellule delimitee par les
        # attaques, ou il ne reste rien a lisser quand la cellule est courte.
        n = len(midi_f)
        bounds = sorted({0, n} | {i for i in onsets if 0 < i < n})
        sm = snapped.copy()
        for a, b in zip(bounds, bounds[1:]):
            sm[a:b] = _median_int(snapped[a:b], 3)
        snapped = np.where(voiced, sm, 0)

    # [debut, fin, demi-ton, longueur d'origine]
    runs: list[list[int]] = []
    for i in range(len(midi_f)):
        if not voiced[i]:
            runs.append([i, i + 1, 0, 1])
        elif (i not in onsets and runs and runs[-1][2] == snapped[i]
              and runs[-1][2] != 0):
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1, int(snapped[i]), 1])
    # Le transitoire d'attaque appartient a la note qu'il annonce. Un segment
    # qui commence sur une attaque mais ne dure pas est la hauteur parasite du
    # transitoire — le detecteur se trompe souvent d'octave sur cette
    # trame-la : on le rend au segment suivant, sinon chaque note breve
    # s'accompagne d'une note fantome une octave plus bas.
    merged: set[int] = set()
    for i, r in enumerate(runs[:-1]):
        if (r[2] != 0 and r[0] in onsets and (r[1] - r[0]) < min_note_frames
                and runs[i + 1][2] != 0 and runs[i + 1][0] not in onsets):
            runs[i + 1][0] = r[0]
            merged.add(i)
    if merged:
        runs = [r for i, r in enumerate(runs) if i not in merged]

    for r in runs:
        r[3] = r[1] - r[0]

    # Absorber les segments trop courts dans un voisin assez long. Trois
    # garde-fous, et aucun n'est superflu :
    #
    # - un segment qui commence sur une ATTAQUE est une vraie note, meme
    #   breve : on n'y touche pas. C'est ce qui sauve doubles et triples
    #   croches ;
    # - la cible est jugee sur sa longueur D'ORIGINE, et les voisins sont ceux
    #   du decoupage D'ORIGINE : une seule passe, pas de reevaluation. Sinon la
    #   cible grossit a chaque absorption, devient un aimant, et avale de
    #   proche en proche tout un trait rapide ou un glissando — la note finale
    #   est alors la mediane de tout ce qu'elle a mange, une hauteur qui n'a
    #   jamais ete jouee ;
    # - un segment court dont les deux voisins sont eux aussi courts n'a nulle
    #   part ou aller : c'est un trait rapide, on le laisse.
    def _long(r):
        return r[2] != 0 and r[3] >= min_note_frames

    absorbed: dict[int, int] = {}  # index du segment court -> index de la cible
    for i, r in enumerate(runs):
        if r[2] == 0 or r[3] >= min_note_frames or r[0] in onsets:
            continue
        cands = [j for j in (i - 1, i + 1)
                 if 0 <= j < len(runs) and _long(runs[j])]
        if cands:
            absorbed[i] = max(cands, key=lambda j: runs[j][3])

    if absorbed:
        for i, j in absorbed.items():
            runs[j][0] = min(runs[j][0], runs[i][0])
            runs[j][1] = max(runs[j][1], runs[i][1])
        runs = [r for i, r in enumerate(runs) if i not in absorbed]

    return [(r[0], r[1], r[2]) for r in runs]


def estimate_tuning(frames: list[Frame], min_note_frames: int = 3,
                    with_confidence: bool = False,
                    onsets: set[int] | None = None):
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
    for start, end, val in _runs(midi_f, voiced, min_note_frames, onsets):
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
    envelope: np.ndarray | None = None,
    onset_threshold_db: float = 1.5,
) -> tuple[list[Frame], list[Note], float, float]:
    """Cale les trames sur des notes tenues.

    tuning_cents=None : mesure le desaccord de la source et le compense.

    envelope : amplitude LINEAIRE par trame (le RMS de la source). Sert a
    reperer les attaques, donc a separer les notes repetees et a proteger les
    notes breves. A defaut, on se rabat sur le volume des trames, plus grossier
    (3 dB par cran). onset_threshold_db <= 0 desactive la detection.

    Retourne (trames, notes, desaccord_utilise, confiance_du_desaccord).
    """
    if not frames:
        return frames, [], 0.0, 0.0

    voiced_a = np.array([f.voiced for f in frames])
    thr = onset_threshold_db
    if envelope is not None and len(envelope) == len(frames):
        lvl = np.asarray(envelope, dtype=float)
        ref = float(lvl.max()) if lvl.size else 0.0
        level_db = 20.0 * np.log10(np.maximum(lvl, ref * 1e-5 + 1e-12) /
                                   max(ref, 1e-12))
    else:
        # Sans le RMS de la source, on se rabat sur le volume des trames. Il
        # est quantifie par crans de 3 dB : un seuil plus fin que le cran n'a
        # aucun sens, chaque ondulation de tremolo passerait pour une attaque.
        # On plancher donc a un cran et demi.
        level_db = frame_levels(frames)
        if thr > 0:
            thr = max(thr, 1.5 * DB_PER_VOLUME_STEP)
    onsets = _onsets(level_db, voiced_a, thr)

    # Passe 1 : mesurer le desaccord (elle fait son propre decoupage).
    # Passe 2 : redecouper avec la hauteur compensee.
    if tuning_cents is None:
        tuning, confidence = estimate_tuning(frames, min_note_frames, True, onsets)
    else:
        tuning, confidence = float(tuning_cents), 1.0
    freqs = frame_freqs(frames)
    voiced = voiced_a
    midi_f = np.array([freq_to_midi(float(f), tuning) if f > 0 else 0.0 for f in freqs])
    runs = _runs(midi_f, voiced, min_note_frames, onsets)

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
