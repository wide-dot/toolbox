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


def test_no_noise_means_no_extra_command():
    """noise=None doit laisser le flux rigoureusement identique a l'existant."""
    a = codegen.frames_to_commands(_tone_frames(20))
    b = codegen.frames_to_commands(_tone_frames(20), noise=None, channel=CHANNEL)
    assert [(c.reg, c.data, c.delay) for c in a] == [(c.reg, c.data, c.delay) for c in b]
    print(f"  {len(a)} commandes, identiques sans couche bruit")


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
