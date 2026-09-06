"""Entrelacement de la couche bruit dans le flux de commandes.

Une seule voie melodique et la section rythme partagent le meme flux : c'est ce
qui permet a un bruitage d'avoir un corps tonal ET des frappes de bruit. Deux
choses doivent tenir : la note ne doit pas etre abimee par la presence du
rythme, et les ecritures rythmiques doivent atterrir sur les bons registres
apres l'addition faite par le driver.
"""

import sys

import numpy as np

from to8sfx import codegen, opll, rhythm

RATE = 44100
CHANNEL = 4


def _tone_frames(n=25, midi=69):
    fnum, block = opll.freq_to_fnum_block(opll.midi_to_freq(midi))
    return [opll.Frame(True, fnum, block, 0, 12) for _ in range(n)]


def test_noise_registers_land_on_the_chip_registers():
    """Apres l'addition du driver, on doit retomber exactement sur $16..$38."""
    noise = [0] * 10
    noise[3] = rhythm.HITS["BD"]
    cmds = codegen.frames_to_commands(_tone_frames(10), noise=noise, channel=CHANNEL)
    seen = {c.reg + CHANNEL if c.reg > 0x0F else c.reg for c in cmds}
    for reg, _ in rhythm.arm_writes(4, 4):
        assert reg in seen, f"registre ${reg:02X} jamais atteint"
    assert opll.REG_RHYTHM in seen, "$0E jamais ecrit"
    print(f"  {len(seen)} registres atteints, armement complet")


def test_hit_is_a_rising_edge():
    """Une frappe est un front montant : le bit doit retomber ensuite, sinon la
    percussion ne se redeclenche jamais."""
    noise = [0, 0, rhythm.HITS["SD"], 0, rhythm.HITS["SD"], 0]
    cmds = codegen.frames_to_commands(_tone_frames(6), noise=noise, channel=CHANNEL)
    vals = [c.data for c in cmds if c.reg == opll.REG_RHYTHM]
    on = rhythm.RHYTHM_ON | rhythm.HITS["SD"]
    assert vals.count(on) == 2, f"deux frappes attendues, ecritures $0E : {vals}"
    assert rhythm.RHYTHM_ON in vals, "le bit de declenchement ne retombe jamais"
    print(f"  {vals.count(on)} fronts montants, relachement present")


def test_tone_survives_the_noise_layer():
    """La note melodique doit garder son niveau quand le rythme s'active."""
    def rms(cmds):
        ev, n = codegen.commands_to_events(cmds, CHANNEL)
        y = opll.render(ev, n)
        a, b = int(0.10 * RATE), int(0.25 * RATE)
        return float(np.sqrt(np.mean(y[a:b] ** 2)))

    plain = rms(codegen.frames_to_commands(_tone_frames(40)))
    noise = [0] * 40
    noise[30] = rhythm.HITS["BD"]
    mixed = rms(codegen.frames_to_commands(_tone_frames(40), noise=noise, channel=CHANNEL))
    assert mixed > plain * 0.8, f"la note est ecrasee : {plain:.4f} -> {mixed:.4f}"
    print(f"  note seule {plain:.4f}, avec rythme {mixed:.4f}")


def test_noise_layer_refuses_channels_taken_by_rhythm_mode():
    """Les voies 6, 7 et 8 sont requisitionnees par le mode rythme : une
    couche bruit dessus effacerait le corps melodique, pas seulement viserait
    un mauvais registre."""
    noise = [0, rhythm.HITS["BD"]]
    for channel in (6, 7, 8):
        try:
            codegen.frames_to_commands(_tone_frames(2), noise=noise, channel=channel)
        except ValueError:
            continue
        raise AssertionError(f"voie {channel} acceptee alors qu'elle est requisitionnee")
    print("  voies 6, 7 et 8 refusees avec la couche bruit")


def test_stream_is_byte_identical_to_before_the_noise_layer():
    """Sans couche bruit, le flux doit etre celui d'AVANT cette tache.

    Reference capturee sur codegen.py au commit df1013e, qui precede
    l'entrelacement du bruit. Comparer deux appels de la fonction actuelle ne
    prouverait rien : avec noise=None ils traversent le meme chemin, donc leur
    egalite est forcee quoi que fasse le code. Seule une reference exterieure,
    figee, detecte une modification inconditionnelle du flux - et c'est de ca
    que depend l'onglet Fichier audio, qui ne doit rien voir de cette tache.

    Si ce test tombe apres un changement volontaire du format des commandes,
    recapturer la reference en connaissance de cause, ne pas l'ajuster a
    l'aveugle pour faire passer la suite.
    """
    frames = [
        opll.Frame(True, 300, 3, 8, 5, attack=True),   # debut de note
        opll.Frame(True, 300, 3, 8, 5, attack=False),  # tenue : rien ne change
        opll.Frame(True, 350, 3, 8, 5, attack=False),  # changement de hauteur
        opll.Frame(True, 350, 3, 4, 5, attack=False),  # changement de volume
        opll.Frame(False, 350, 3, 4, 5),               # note coupee
        opll.Frame(True, 400, 4, 10, 5, attack=True),  # nouvelle attaque
    ]
    expected = [
        (48, 88, 0), (16, 44, 0), (32, 23, 2), (16, 94, 1), (48, 84, 1),
        (32, 7, 1), (48, 90, 0), (16, 144, 0), (32, 25, 1),
    ]
    cmds = codegen.frames_to_commands(frames)
    got = [(c.reg, c.data, c.delay) for c in cmds]
    assert got == expected, f"flux modifie sans couche bruit : {got}"
    print(f"  {len(got)} commandes, identiques au flux d'avant la couche bruit")


def test_channel_is_ignored_without_a_noise_track():
    """noise=None doit laisser channel sans effet : il ne doit pas fuir hors
    de sa garde `if noise is not None`. Ce test ne prouve PAS la
    non-regression du flux (voir test_stream_is_byte_identical_to_before_the_noise_layer
    pour ca) : avec noise=None les deux appels traversent de toute facon le
    meme chemin, donc leur egalite est forcee quoi que fasse le code."""
    a = codegen.frames_to_commands(_tone_frames(20))
    b = codegen.frames_to_commands(_tone_frames(20), noise=None, channel=CHANNEL)
    assert [(c.reg, c.data, c.delay) for c in a] == [(c.reg, c.data, c.delay) for c in b]
    print(f"  {len(a)} commandes, channel sans effet quand noise=None")


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
