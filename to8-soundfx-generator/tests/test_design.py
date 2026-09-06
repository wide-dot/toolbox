"""Le modele de son : enveloppe, hauteur, arpege, bruit."""

import sys

from to8sfx import design, opll, rhythm


def _midis(frames):
    return [round(opll.freq_to_midi(opll.fnum_block_to_freq(f.fnum, f.block)))
            for f in frames if f.voiced]


def test_duration_is_the_envelope():
    """La duree n'est pas un reglage : elle vaut attaque + tenue + chute. En
    faire un parametre independant permettrait de la mettre en contradiction
    avec l'enveloppe qui la compose."""
    p = design.SfxParams(attack_frames=2, hold_frames=3, decay_frames=10)
    assert p.duration_frames == 15
    frames, _ = design.render(p)
    assert len(frames) == 15, f"{len(frames)} trames pour une duree de 15"
    print("  duree = attaque + tenue + chute")


def test_envelope_rises_then_falls():
    p = design.SfxParams(attack_frames=4, hold_frames=2, decay_frames=8,
                         vol_peak=0, vol_end=15)
    frames, _ = design.render(p)
    vols = [f.volume for f in frames]          # 0 = fort, 15 = faible
    assert vols[0] > vols[3], f"pas d'attaque : {vols[:5]}"
    assert vols[4] == 0 and vols[5] == 0, f"pas de palier : {vols}"
    assert vols[-1] >= 14, f"pas de chute : {vols[-3:]}"
    print(f"  enveloppe : {vols}")


def test_slide_delta_bends_the_glide():
    """L'inflexion est ce qui donne le glissement qui ralentit. Sans elle, une
    droite ; avec, une courbe."""
    straight, _ = design.render(design.SfxParams(
        attack_frames=0, hold_frames=0, decay_frames=20,
        f_start=1200, slide=-0.5, slide_delta=0.0))
    bent, _ = design.render(design.SfxParams(
        attack_frames=0, hold_frames=0, decay_frames=20,
        f_start=1200, slide=-0.5, slide_delta=0.04))
    a, b = _midis(straight), _midis(bent)
    assert a[-1] < b[-1], f"l'inflexion ne redresse rien : {a[-1]} vs {b[-1]}"
    mid = len(a) // 2
    assert abs(a[mid] - b[mid]) < abs(a[-1] - b[-1]), "l'ecart devrait croitre"
    print(f"  droit {a[0]}->{a[-1]}, inflechi {b[0]}->{b[-1]}")


def test_arpeggio_visits_every_step():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=12,
                         f_start=440, slide=0.0, arp_steps=(0, 4, 7),
                         arp_frames=1)
    frames, _ = design.render(p)
    got = sorted(set(_midis(frames)))
    assert len(got) == 3, f"{len(got)} hauteurs au lieu de 3 : {got}"
    assert got[1] - got[0] == 4 and got[2] - got[0] == 7, got
    print(f"  arpege : {[opll.midi_name(m) for m in got]}")


def test_arpeggio_off_when_arp_frames_is_zero():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=12,
                         f_start=440, slide=0.0, arp_steps=(0, 4, 7),
                         arp_frames=0)
    frames, _ = design.render(p)
    assert len(set(_midis(frames))) == 1, "l'arpege joue alors qu'il est eteint"
    print("  arp_frames=0 eteint bien l'arpege")


def test_noise_track_is_none_when_layer_is_off():
    """La couche bruit est desactivee par defaut : le mode rythme requisitionne
    les voies 6-8 et la musique du jeu peut s'en servir."""
    frames, noise = design.render(design.SfxParams())
    assert noise is None, "la couche bruit est active par defaut"
    print("  couche bruit eteinte par defaut")


def test_noise_burst_density_falls():
    """Une rafale dont la densite retombe : c'est ce qui fait une explosion."""
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=40,
                         noise_on=True, noise_kit=("BD", "SD"), noise_hits=16,
                         noise_spread_frames=40, noise_accel=-0.8)
    _, noise = design.render(p)
    assert noise is not None and len(noise) == 40
    first = sum(1 for v in noise[:20] if v)
    last = sum(1 for v in noise[20:] if v)
    assert first > last, f"la densite ne retombe pas : {first} puis {last}"
    assert all(v & ~0x1F == 0 for v in noise), "un masque deborde des bits 0-4"
    print(f"  rafale : {first} frappes puis {last}")


def test_repeat_restarts_the_pattern():
    p = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=20,
                         f_start=880, slide=-0.4, repeat_frames=5)
    frames, _ = design.render(p)
    m = _midis(frames)
    assert m[0] == m[5] == m[10], f"la repetition ne relance rien : {m}"
    assert any(f.attack for f in frames[5:6]), "pas de re-attaque a la relance"
    print(f"  repetition tous les 5 : {m[:12]}")


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
