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


def test_channels_taken_by_rhythm_mode_are_refused():
    """Les voies 6, 7 et 8 sont requisitionnees par le mode rythme lui-meme :
    une couche melodique dessus serait effacee, pas simplement mal adressee."""
    for channel in (6, 7, 8):
        try:
            rhythm.check_channel(channel)
        except ValueError:
            continue
        raise AssertionError(f"voie {channel} acceptee alors qu'elle est hors plage")
    for channel in range(0, 6):
        rhythm.check_channel(channel)  # ne doit pas lever
    print("  voies 6 a 8 refusees, 0 a 5 acceptees")


def test_rhythm_mode_erases_the_melodic_voices_it_takes():
    """La limite de MAX_CHANNEL est materielle, pas seulement d'adressage.

    Le mode rythme requisitionne les voies 6, 7 et 8. Une note melodique posee
    sur l'une d'elles n'est pas degradee : elle disparait. C'est ce qui fixe la
    limite a 5 et non a 6, et cette mesure est la seule justification de la
    constante.
    """
    def rms(channel, with_rhythm):
        ev = [(0, 0x30 + channel, 0xF0), (0, 0x10 + channel, 0x2A),
              (0, 0x20 + channel, 0x1A)]
        if with_rhythm:
            ev += [(0, r, v) for r, v in rhythm.arm_writes(4, 4)]
            ev.append((0, opll.REG_RHYTHM, rhythm.RHYTHM_ON))
        y = opll.render(ev, int(0.5 * RATE), RATE)
        return float(np.sqrt(np.mean(y[int(0.15 * RATE):int(0.40 * RATE)] ** 2)))

    for channel in range(0, rhythm.MAX_CHANNEL + 1):
        assert rms(channel, True) > rms(channel, False) * 0.5, (
            f"voie {channel} autorisee mais effacee par le mode rythme")
    for channel in (6, 7, 8):
        assert rms(channel, True) < rms(channel, False) * 0.1, (
            f"voie {channel} survit au mode rythme : la limite est trop stricte")
    print(f"  voies 0 a {rhythm.MAX_CHANNEL} preservees, 6 a 8 effacees")


def test_encode_refuses_a_rhythm_register_on_an_out_of_range_channel():
    """Le garde doit etre DANS encode, pas seulement disponible a cote.

    Sans ce test, retirer check_channel de encode laisserait toute la suite au
    vert pendant que encode(0x16, 7) rendrait $0F : le driver l'ecrirait
    verbatim et viserait le registre de controle du rythme au lieu de la
    hauteur de la grosse caisse. Silencieux, et faux.
    """
    for channel in (7, 8):
        for reg, _val in rhythm.arm_writes(noise_pitch=4, noise_vol=4):
            try:
                rhythm.encode(reg, channel)
            except ValueError:
                continue
            raise AssertionError(
                f"encode(${reg:02X}, {channel}) n'a pas leve alors que la voie "
                "est hors plage")
    print("  encode refuse les registres rythmiques au-dela de la voie 5")


def test_any_channel_outside_the_chip_is_refused():
    """La voie part dans le deuxieme octet de l'en-tete du bloc, et le driver
    l'ajoute aux numeros de registres. Une valeur aberrante s'y ecrivait telle
    quelle : le bruitage allait ecrire n'importe ou dans la puce, sans un mot.

    C'est la contrainte GENERALE de la puce, distincte de celle du mode rythme :
    la voie 7 existe, elle est seulement interdite a la couche bruit.
    """
    for voie in (-1, 9, 42):
        try:
            rhythm.check_any_channel(voie)
        except ValueError:
            continue
        raise AssertionError(f"voie {voie} acceptee alors qu'elle n'existe pas")
    for voie in range(rhythm.CHANNEL_MIN, rhythm.CHANNEL_MAX + 1):
        rhythm.check_any_channel(voie)  # ne doit pas lever
    print(f"  voies {rhythm.CHANNEL_MIN} a {rhythm.CHANNEL_MAX} acceptees, "
          "au-dela refusees")


def test_noise_check_reports_the_general_constraint_first():
    """Sur une voie inexistante, "voie 42 inexistante" est plus utile que
    "couche bruit impossible sur la voie 42", qui laisserait croire qu'il
    suffirait de couper les percussions."""
    try:
        rhythm.check_channel(42)
    except ValueError as e:
        assert "inexistante" in str(e), str(e)
        print("  la contrainte generale est signalee avant celle du bruit")
        return
    raise AssertionError("voie 42 acceptee par check_channel")


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
