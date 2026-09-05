"""Verrouille les constantes materielles contre l'emulateur.

Lancer : python3 -m tests.test_opll  (depuis la racine de l'outil)
"""

import sys

import numpy as np

from to8sfx import opll

RATE = 44100


def _tone(fnum, block, inst=3, vol=0, secs=1.0):
    ev = [
        (0, opll.REG_INST_VOL, (inst << 4) | vol),
        (0, opll.REG_FNUM_LO, fnum & 0xFF),
        (0, opll.REG_BLOCK, ((fnum >> 8) & 1) | (block << 1) | opll.KEY_ON),
    ]
    return opll.render(ev, int(RATE * secs), RATE)


def _f0(x, expected):
    """Periode mesuree, cherchee autour de la periode attendue (evite les
    erreurs d'octave qui n'ont rien a voir avec la formule testee)."""
    x = x[RATE // 5 :]
    x = x - x.mean()
    n = len(x)
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, 2 * n)) ** 2)[:n]
    ac /= ac[0] + 1e-12
    per = RATE / expected
    lo, hi = int(per * 0.8), int(per * 1.25) + 2
    lo, hi = max(2, lo), min(n - 2, hi)
    k = lo + int(np.argmax(ac[lo:hi]))
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    den = a - 2 * b + c
    d = 0.5 * (a - c) / den if den != 0 else 0.0
    return RATE / (k + d)


def test_frequency_formula():
    """f = fnum * clk / 72 / 2**(19-block), verifiee sur l'emulateur."""
    cases = [(256, 4), (300, 3), (511, 5), (400, 6), (100, 7), (290, 4), (450, 2)]
    worst = 0.0
    for fnum, block in cases:
        want = opll.fnum_block_to_freq(fnum, block)
        if want < 60:  # trop bas pour une mesure fiable sur 0.8 s
            continue
        got = _f0(_tone(fnum, block), want)
        err = abs(got - want) / want * 100
        worst = max(worst, err)
        assert err < 0.5, f"fnum={fnum} block={block}: {want:.2f} != {got:.2f} Hz"
    print(f"  formule frequence : ecart max {worst:.3f} %")


def test_rom_patches_close_to_engine_table():
    """Compare les patchs ROM d'emu2413 a la table en commentaire de
    engine/sound/soundFX.asm.

    Les deux divergent d'un quartet ici ou la sur une partie des instruments :
    la table du moteur est l'ancienne table qui circule dans la doc, celle
    d'emu2413 est relevee sur puce reelle et fait aujourd'hui reference. Aucune
    des deux n'est utilisee par le driver (il n'ecrit jamais de patch, sauf
    commande $FF explicite), donc l'ecart est sans consequence sur le jeu ; il
    ne touche que la fidelite du preview. On verifie seulement qu'on lit bien le
    jeu de patchs YM2413 et pas celui du VRC7 ou du 281B."""
    engine_table = {
        1: "71 61 1E 17 D0 78 00 17",
        2: "13 41 1A 0D D8 F7 23 13",
        3: "13 01 99 00 F2 C4 11 23",
        4: "31 61 0E 07 A8 64 70 27",
        5: "32 21 1E 06 E0 76 00 28",
        6: "31 22 16 05 E0 71 00 18",
        7: "21 61 1D 07 82 81 10 07",
        8: "23 21 2D 14 A2 72 00 07",
        9: "61 61 1B 06 64 65 10 17",
        10: "41 61 0B 18 85 F7 71 07",
        11: "13 01 83 11 FA E4 10 04",
        12: "17 C1 24 07 F8 F8 22 12",
        13: "61 50 0C 05 C2 F5 20 42",
        14: "01 01 55 03 C9 95 03 02",
    }
    diffs, total_bytes = [], 0
    for num, want in engine_table.items():
        w = bytes(int(b, 16) for b in want.split())
        g = opll.rom_patch_dump(num)
        nd = sum(1 for a, b in zip(w, g) if a != b)
        total_bytes += nd
        if nd:
            diffs.append(f"    inst {num:2d} {opll.INSTRUMENTS[num]:18s} {nd} octet(s)")
    mean = total_bytes / len(engine_table)
    assert mean < 3.0, (
        f"{mean:.1f} octets divergents par patch : ce n'est probablement pas le "
        "jeu de patchs YM2413"
    )
    print(
        f"  patchs ROM : {len(engine_table) - len(diffs)}/{len(engine_table)} identiques "
        f"a la table du moteur, {mean:.1f} octet(s) d'ecart en moyenne"
    )
    for d in diffs:
        print(d)


def test_volume_is_3db_per_step():
    """Chaque cran de volume doit attenuer d'environ 3 dB."""
    rms = []
    for vol in range(0, 8):
        x = _tone(290, 4, inst=3, vol=vol, secs=0.5)[RATE // 10 :]
        rms.append(np.sqrt(np.mean(x**2)))
    steps = [20 * np.log10(rms[i] / rms[i + 1]) for i in range(len(rms) - 1)]
    mean = float(np.mean(steps))
    assert 2.5 < mean < 3.5, f"pas de volume mesure a {mean:.2f} dB"
    print(f"  volume : {mean:.2f} dB par cran (attendu 3)")


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
