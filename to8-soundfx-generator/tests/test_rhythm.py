"""Section rythme du YM2413 : la seule source de bruit de la puce.

Le driver ecrit les registres <= $0F tels quels et ajoute le numero de voie aux
autres (engine/sound/soundFX.asm, etiquette @NotCustom). Les registres des voies
rythmiques sont au-dessus de $0F : il faut donc EMETTRE reg - voie pour que la
puce recoive reg. Ces tests verrouillent cet aller-retour, parce qu'une erreur
ici ne fait pas de bruit : elle ecrit dans un autre registre, en silence.
"""

import sys

import numpy as np

from to8sfx import opll, rhythm

RATE = 44100


def _driver_sees(emitted_reg, channel):
    """Ce que la puce recoit, en rejouant la regle du driver."""
    return emitted_reg if emitted_reg <= 0x0F else emitted_reg + channel


def test_encode_round_trips_through_the_driver_rule():
    for channel in range(0, rhythm.MAX_CHANNEL + 1):
        for reg, _val in rhythm.arm_writes(noise_pitch=4, noise_vol=4):
            emitted = rhythm.encode(reg, channel)
            assert _driver_sees(emitted, channel) == reg, (
                f"voie {channel} : emis ${emitted:02X} -> "
                f"${_driver_sees(emitted, channel):02X}, voulu ${reg:02X}")
    print(f"  aller-retour verifie sur les voies 0 a {rhythm.MAX_CHANNEL}")


def test_rhythm_control_register_is_never_shifted():
    """$0E est <= $0F : il doit passer verbatim depuis n'importe quelle voie."""
    for channel in range(0, 9):
        assert rhythm.encode(opll.REG_RHYTHM, channel) == opll.REG_RHYTHM
    print("  $0E passe verbatim depuis toutes les voies")


def test_channels_above_six_are_refused():
    """A partir de la voie 7, $16 - 7 = $0F retombe dans la plage ecrite
    verbatim et viserait le registre de controle du rythme."""
    for channel in (7, 8):
        try:
            rhythm.check_channel(channel)
        except ValueError:
            continue
        raise AssertionError(f"voie {channel} acceptee alors qu'elle est hors plage")
    for channel in range(0, 7):
        rhythm.check_channel(channel)  # ne doit pas lever
    print("  voies 7 et 8 refusees, 0 a 6 acceptees")


def test_each_percussion_is_actually_noisy():
    """La caisse claire et la charleston doivent produire du bruit, pas un son
    pur : c'est toute la raison d'etre de cette couche."""
    def flatness(mask):
        ev = [(0, r, v) for r, v in rhythm.arm_writes(4, 4)]
        ev.append((0, opll.REG_RHYTHM, rhythm.RHYTHM_ON))
        ev.append((int(0.02 * RATE), opll.REG_RHYTHM, rhythm.RHYTHM_ON | mask))
        ev.append((int(0.10 * RATE), opll.REG_RHYTHM, rhythm.RHYTHM_ON))
        y = opll.render(ev, int(0.5 * RATE), RATE)[int(0.02 * RATE):int(0.25 * RATE)]
        p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2 + 1e-20
        return float(np.exp(np.mean(np.log(p))) / np.mean(p))

    sd = flatness(rhythm.HITS["SD"])
    hh = flatness(rhythm.HITS["HH"])
    assert sd > 0.15, f"caisse claire pas assez bruitee : platitude {sd:.3f}"
    assert hh > 0.05, f"charleston pas assez bruitee : platitude {hh:.3f}"
    print(f"  platitude spectrale : caisse claire {sd:.3f}, charleston {hh:.3f}")


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
