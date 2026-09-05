"""Analyse d'un fichier audio : ce que la fenetre d'integration decide.

Le detecteur de hauteur travaille sur une fenetre. Si elle est plus longue
qu'une note, elle en enjambe plusieurs et tout s'ecroule d'un coup : trames
declarees muettes (des trous dans le rendu) et hauteurs aberrantes, tenues sur
tout le passage. Ces tests verrouillent le dimensionnement.
"""

import sys

import numpy as np

from to8sfx import analyze as an
from to8sfx import opll

RATE = 44100
RNG = np.random.default_rng(7)


def _pluck(freq, n, decay=60.0):
    t = np.arange(n) / RATE
    x = sum(a * np.sin(2 * np.pi * k * freq * t)
            for k, a in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.2)))
    return x * np.exp(-t * decay)


def _arpeggio(note_ms, midis=(69, 72, 76, 72), secs=1.2, noise=0.0):
    """Un trait rapide monophonique : une note breve apres l'autre."""
    seq = list(midis) * int(secs / (note_ms / 1000.0) / len(midis) + 1)
    x = np.concatenate([
        _pluck(opll.midi_to_freq(m), int(note_ms / 1000.0 * RATE)) * np.exp(-k * 0.02)
        for k, m in enumerate(seq)])
    return (x * 0.4 + RNG.normal(0, noise, len(x))).astype(np.float32)


def _tone(freq, secs, noise=0.0):
    t = np.arange(int(secs * RATE)) / RATE
    x = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(4 * np.pi * freq * t)
    return (x * 0.3 + RNG.normal(0, noise, len(t))).astype(np.float32)


def _accuracy(a, midis):
    """Part des trames dont la classe de hauteur est juste, sur le total."""
    want = {m % 12 for m in midis}
    ok = sum(1 for f, v in zip(a.f0, a.voiced)
             if v and round(opll.freq_to_midi(float(f))) % 12 in want)
    return a.voiced.mean(), ok / max(a.n_frames, 1)


def test_fast_arpeggio_is_not_full_of_holes():
    """Un trait a une note toutes les 20 ms doit s'analyser, pas se trouer.

    C'est le cas qui a revele le probleme : avec une fenetre de 46 ms, 25 %
    seulement des trames etaient voisees et le detecteur rendait une note
    fausse, unique, repetee — la periode de repetition du trait prise pour sa
    hauteur.
    """
    a = an.analyze(_arpeggio(20), RATE)
    voiced, acc = _accuracy(a, (69, 72, 76))
    assert voiced > 0.9, f"{voiced*100:.0f} % de trames voisees seulement"
    assert acc > 0.9, f"{acc*100:.0f} % de trames justes seulement"
    names = {opll.midi_name(round(opll.freq_to_midi(float(f))))
             for f, v in zip(a.f0, a.voiced) if v}
    assert len(names) >= 3, f"une seule hauteur detectee : {names}"
    print(f"  arpege 20 ms : {voiced*100:.0f} % voisees, {acc*100:.0f} % justes, "
          f"{len(names)} hauteurs")


def test_fast_arpeggio_survives_noise():
    """Et il doit y survivre avec du bruit : la fenetre courte ne doit pas
    avoir ete payee par une perte de robustesse."""
    a = an.analyze(_arpeggio(20, noise=0.04), RATE)
    voiced, acc = _accuracy(a, (69, 72, 76))
    assert voiced > 0.9 and acc > 0.9, f"{voiced*100:.0f} % voisees, {acc*100:.0f} % justes"
    print(f"  arpege bruite : {voiced*100:.0f} % voisees, {acc*100:.0f} % justes")


def test_note_per_frame_is_fully_recovered():
    """Un trait a une note par trame doit ressortir entier, note pour note.

    C'est la limite dure du format — le driver ne sait rien representer de plus
    court que sa trame de 20 ms — et rien en amont ne doit la rabaisser. Trois
    choses la rabaissaient : le filtre median de l'analyse, celui du mode
    melodique, et l'ecart minimal impose entre deux attaques.

    Le contrat : lissage a 1 et duree mini d'une note a 1 trame, l'utilisateur
    declare qu'il veut ce debit-la et il l'obtient.
    """
    from to8sfx import melody

    motif = (69, 72, 76, 81, 76, 72)
    x = _arpeggio(20, midis=motif, secs=1.2)
    a = an.analyze(x, RATE)
    frames = an.to_frames(a, instrument=15, smooth=1)
    i0, i1 = an.trim_bounds(frames)
    frames, env = frames[i0:i1], a.rms[i0:i1]
    _, notes, _, _ = melody.quantize(frames, min_note_frames=1, envelope=env)

    assert len(notes) == len(frames), f"{len(notes)} notes pour {len(frames)} trames"
    got = [n.midi for n in notes]
    assert got[:12] == list(motif) * 2, [opll.midi_name(m) for m in got[:12]]
    assert all(n.frames == 1 for n in notes), "des notes ont ete fusionnees"
    print(f"  {len(notes)} notes sur {len(frames)} trames, motif exact")


def test_no_phantom_note_on_the_first_frame():
    """Le raffinement parabolique de YIN pouvait sortir de la plage demandee et
    rendre une hauteur au-dessus de fmax sur la premiere trame d'un son."""
    a = an.analyze(_arpeggio(20), RATE, fmax=5000.0)
    top = max((float(f) for f, v in zip(a.f0, a.voiced) if v), default=0.0)
    assert top <= 5000.0, f"hauteur detectee a {top:.0f} Hz, au-dessus de fmax"
    print(f"  hauteur maximale detectee : {top:.0f} Hz (fmax 5000)")


def test_low_note_still_detected():
    """La contrepartie a verifier : la plage de frequences ne depend pas de la
    fenetre. Une note a 61,7 Hz — trois octaves sous l'arpege — doit rester
    detectee, sinon on aurait juste deplace le probleme."""
    a = an.analyze(_tone(61.7, 1.0), RATE)
    voiced, acc = _accuracy(a, (35,))
    assert voiced > 0.9 and acc > 0.9, f"{voiced*100:.0f} % voisees, {acc*100:.0f} % justes"
    print(f"  note grave 61,7 Hz : {voiced*100:.0f} % voisees, {acc*100:.0f} % justes")


def test_sustained_note_stays_stable():
    """Et une tenue bruitee ne doit pas se mettre a papillonner."""
    a = an.analyze(_tone(440.0, 1.0, noise=0.06), RATE)
    voiced, acc = _accuracy(a, (69,))
    assert voiced > 0.9 and acc > 0.9, f"{voiced*100:.0f} % voisees, {acc*100:.0f} % justes"
    print(f"  tenue 440 Hz bruitee : {voiced*100:.0f} % voisees, {acc*100:.0f} % justes")


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
