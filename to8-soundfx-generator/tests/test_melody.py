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


def _notes_frames(seq, instrument=12, decay=1.2, glitch=False):
    """seq = [(midi, n_trames)] -> trames avec une attaque percussive par note.

    Le volume repart de 0 (fort) a chaque note et redescend : c'est
    l'enveloppe qui porte les debuts de note, et c'est la SEULE information
    capable de separer deux notes de meme hauteur.

    glitch=True ajoute une erreur d'octave d'une trame sur chaque attaque,
    comme en produit vraiment YIN dans le transitoire.
    """
    out = []
    for k, (midi, n) in enumerate(seq):
        for i in range(n):
            m = midi - 12 if (glitch and k > 0 and i == 0) else midi
            fnum, block = opll.freq_to_fnum_block(opll.midi_to_freq(m))
            out.append(opll.Frame(True, fnum, block, int(min(15, round(i * decay))),
                                  instrument))
    return out


def test_repeated_notes_are_separated():
    """Quatre doubles croches sur la meme note doivent rester quatre notes.

    Le decoupage par hauteur seule les fusionne forcement : rien ne distingue
    deux D5 consecutifs d'un D5 tenu, sauf l'enveloppe.
    """
    _, notes, _, _ = melody.quantize(_notes_frames([(74, 6)] * 4))
    assert len(notes) == 4, f"{len(notes)} note(s) au lieu de 4"
    assert all(n.midi == 74 for n in notes), [n.name for n in notes]
    print(f"  4 doubles croches sur D5 : {melody.describe(notes)}")


def test_fast_notes_survive_next_to_a_long_note():
    """Une suite de notes courtes voisine d'une note tenue doit survivre.

    L'absorption des segments courts fait grossir sa cible, qui devient un
    aimant : elle avale alors tout un trait rapide de proche en proche, et la
    note finale est la mediane de tout ce qu'elle a mange - une hauteur qui
    n'a jamais ete jouee.
    """
    seq = [(72, 25), (79, 3), (81, 3), (83, 3), (84, 3), (76, 25)]
    _, notes, _, _ = melody.quantize(_notes_frames(seq, glitch=True))
    got = [n.midi for n in notes]
    assert got == [m for m, _ in seq], (
        f"{[opll.midi_name(m) for m in got]} != "
        f"{[opll.midi_name(m) for m, _ in seq]}")
    print(f"  trait rapide preserve : {melody.describe(notes)}")


def test_onset_threshold_tradeoff():
    """Le seuil d'attaque par defaut doit tenir les deux bords a la fois.

    Trop haut, les notes breves d'un trait rapide passent inapercues ; trop
    bas, le tremolo d'une note tenue est pris pour une suite d'attaques et la
    note se decoupe toute seule. Mesure : le defaut doit rendre les 8 notes
    d'un trait de doubles croches ET garder d'un bloc une tenue a 4 dB de
    tremolo.
    """
    fast = _notes_frames([(72, 3), (74, 3), (76, 3), (77, 3),
                          (79, 3), (77, 3), (76, 3), (74, 3)], decay=0.8)
    _, notes, _, _ = melody.quantize(fast)
    assert len(notes) == 8, f"trait rapide : {melody.describe(notes)}"

    fnum, block = opll.freq_to_fnum_block(opll.midi_to_freq(69))
    trem = [opll.Frame(True, fnum, block,
                       int(round(2 + 0.66 * np.sin(i * 0.6))), 12)  # +-4 dB
            for i in range(75)]
    _, notes, _, _ = melody.quantize(trem)
    assert len(notes) == 1, f"tenue avec tremolo decoupee en {len(notes)} notes"
    print("  seuil par defaut : trait rapide entier, tenue non decoupee")


def test_pitch_glitch_is_still_absorbed():
    """Mais une erreur d'octave d'une trame au milieu d'une note tenue, non.

    C'est la contrepartie : si plus rien n'est absorbe, chaque hesitation du
    detecteur devient une note parasite.
    """
    frames = _notes_frames([(72, 25)])
    frames[12].fnum, frames[12].block = opll.freq_to_fnum_block(opll.midi_to_freq(60))
    _, notes, _, _ = melody.quantize(frames)
    assert len(notes) == 1, f"{melody.describe(notes)}"
    assert notes[0].midi == 72, notes[0].name
    print("  erreur d'octave isolee toujours nettoyee")


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
