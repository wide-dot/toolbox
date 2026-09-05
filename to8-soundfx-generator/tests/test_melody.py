"""Mode melodique : calage sur les notes, re-attaque, compression."""

import sys

import numpy as np

from to8sfx import codegen, melody, opll

RATE = 44100
JINGLE = [(69, 10), (72, 10), (76, 10), (81, 16)]  # A4 C5 E5 A5


def _frames(vibrato_cents=42.0, detune_cents=0.0, instrument=12, volume=3):
    """Un jingle avec du vibrato et un desaccord, comme une vraie prise."""
    out = []
    for midi, n in JINGLE:
        base = opll.midi_to_freq(midi) * 2 ** (detune_cents / 1200.0)
        for i in range(n):
            f = base * 2 ** (np.sin(i * 0.9) * vibrato_cents / 1200.0)
            fnum, block = opll.freq_to_fnum_block(float(f))
            out.append(opll.Frame(True, fnum, block, volume, instrument))
    return out


def test_notes_are_recovered_through_vibrato():
    """Le vibrato ne doit pas faire papillonner la note d'une trame a l'autre."""
    frames, notes, _, _ = melody.quantize(_frames(vibrato_cents=45.0))
    got = [n.name for n in notes]
    want = [opll.midi_name(m) for m, _ in JINGLE]
    assert got == want, f"{got} != {want}"
    lengths = [n.frames for n in notes]
    assert lengths == [n for _, n in JINGLE], lengths
    print(f"  notes retrouvees : {' '.join(got)}")


def test_detuned_source_is_compensated():
    """Une prise desaccordee de 40 cents doit donner les memes notes."""
    frames, notes, tuning, conf = melody.quantize(_frames(detune_cents=40.0))
    got = [n.name for n in notes]
    want = [opll.midi_name(m) for m, _ in JINGLE]
    assert got == want, f"{got} != {want} (accordage mesure {tuning:.0f} cents)"
    assert 25 < tuning < 55, f"desaccord mal mesure : {tuning:.1f} cents"
    print(f"  desaccord mesure {tuning:+.0f} cents, notes correctes")


def test_melodic_mode_compresses():
    """Une note tenue = une commande longue, pas une par trame."""
    frames = _frames()
    raw, _, _ = codegen.fit_to_budget(frames)
    q, _, _, _ = melody.quantize(frames)
    mel, _, _ = codegen.fit_to_budget(q, quantize_pitch=False)
    r, m = codegen.stats(raw)["bytes"], codegen.stats(mel)["bytes"]
    assert m < r / 2, f"compression insuffisante : {r} -> {m} octets"
    print(f"  {r} -> {m} octets ({r/m:.1f}x)")


def test_retrigger_restarts_envelope():
    """La re-attaque doit relancer l'enveloppe, pas enchainer en legato.

    Mesure sur l'emulateur avec l'instrument 3 (piano, enveloppe percussive) :
    sans re-attaque la deuxieme note poursuit la decroissance de la premiere.
    """
    def render(retrigger):
        fr = []
        for midi, n in [(69, 25), (76, 25)]:
            fnum, block = opll.freq_to_fnum_block(opll.midi_to_freq(midi))
            for i in range(n):
                fr.append(opll.Frame(True, fnum, block, 0, 3,
                                     attack=(retrigger and i == 0)))
        cmds = codegen.frames_to_commands(fr)
        ev, ns = codegen.commands_to_events(cmds, 4)
        return opll.render(ev, ns)

    b = int(25 * RATE / 50)
    win = int(0.05 * RATE)
    ratios = {}
    for retrig in (False, True):
        y = render(retrig)
        before = np.sqrt((y[b - win : b] ** 2).mean())
        after = np.sqrt((y[b : b + win] ** 2).mean())
        ratios[retrig] = after / max(before, 1e-9)
    assert ratios[False] < 1.2, f"sans re-attaque la note repart ({ratios[False]:.2f})"
    assert ratios[True] > 1.8, f"la re-attaque ne relance rien ({ratios[True]:.2f})"
    print(f"  legato x{ratios[False]:.2f} / re-attaque x{ratios[True]:.2f}")


def test_glissando_is_not_collapsed():
    """Un balayage continu doit donner une suite de notes, pas une seule.

    L'absorption des segments courts ne doit mordre que sur les
    papillonnements en bord d'une note tenue. Si elle mange aussi les
    glissandos, tout un balayage se reduit a sa mediane.
    """
    from to8sfx import parametric
    frames = parametric.sweep(parametric.SweepParams(
        duration_ms=420, f_start=440, f_end=1760, pitch_curve="exp",
        vol_start=3, vol_end=6, instrument=12))
    _, notes, _, _ = melody.quantize(frames)
    assert len(notes) >= 8, f"glissando ecrase en {len(notes)} note(s)"
    midis = [n.midi for n in notes]
    assert midis == sorted(midis), f"la montee n'est pas monotone : {midis}"
    assert midis[-1] - midis[0] >= 20, f"amplitude perdue : {midis[0]} -> {midis[-1]}"
    print(f"  glissando : {len(notes)} notes, "
          f"{opll.midi_name(midis[0])} -> {opll.midi_name(midis[-1])}")


def test_scale_forcing():
    """Forcer une gamme doit ramener les notes dans la gamme."""
    _, notes, _, _ = melody.quantize(_frames(), scale="penta-mineure", root=9)  # A
    allowed = {(9 + d) % 12 for d in melody.SCALES["penta-mineure"]}
    off = [n.name for n in notes if n.midi % 12 not in allowed]
    assert not off, f"notes hors gamme : {off}"
    print(f"  penta-mineure de A : {' '.join(n.name for n in notes)}")


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
