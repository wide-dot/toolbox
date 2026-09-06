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


def test_envelope_is_correct_when_a_phase_lasts_one_frame():
    """Une phase d'une seule trame doit quand meme atteindre sa cible.

    C'est le cas PAR DEFAUT du dataclass (attack_frames=1) et la borne basse de
    decay_frames. Une rampe qui ne porte que son point de depart laissait la
    trame d'attaque en silence complet, puis sautait au pic : le son ne
    demarrait qu'a la trame suivante.
    """
    p = design.SfxParams(attack_frames=1, hold_frames=2, decay_frames=4,
                         vol_peak=0, vol_end=15)
    frames, _ = design.render(p)
    vols = [f.volume for f in frames]
    assert vols[0] == 0, f"l'attaque d'une trame n'atteint pas le pic : {vols}"
    assert vols[-1] == 15, f"la chute n'atteint pas vol_end : {vols}"

    court = design.SfxParams(attack_frames=0, hold_frames=0, decay_frames=1,
                             vol_peak=0, vol_end=15)
    frames, _ = design.render(court)
    assert [f.volume for f in frames] == [15], [f.volume for f in frames]
    print(f"  attaque d'une trame : {vols}")


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


def test_randomize_is_deterministic():
    """Meme graine, memes parametres : sans quoi l'historique et la banque ne
    veulent rien dire."""
    for cat in design.CATEGORIES:
        a = design.randomize(cat, seed=1234)
        b = design.randomize(cat, seed=1234)
        assert a.to_dict() == b.to_dict(), f"{cat} n'est pas deterministe"
    c = design.randomize("tir", seed=1)
    d = design.randomize("tir", seed=2)
    assert c.to_dict() != d.to_dict(), "deux graines donnent le meme son"
    print(f"  {len(design.CATEGORIES)} categories, tirage deterministe")


def test_mutate_respects_locks_and_bounds():
    base = design.randomize("explosion", seed=7)
    locked = {"instrument", "f_start", "decay_frames"}
    m = design.mutate(base, amount=0.8, locked=locked, seed=3)
    for k in locked:
        assert getattr(m, k) == getattr(base, k), f"{k} a bouge malgre son cadenas"
    for k, (lo, hi) in design.BOUNDS.items():
        v = getattr(m, k)
        assert lo <= v <= hi, f"{k} = {v} hors de [{lo}, {hi}]"
    assert m.to_dict() != base.to_dict(), "la mutation n'a rien change"
    print(f"  {len(locked)} cadenas tenus, toutes les bornes respectees")


def test_every_category_fits_the_budget():
    """Sur 200 tirages par categorie, aucun ne doit ressortir tronque.

    Verifier qu'aucun ne depasse 255 commandes ne prouverait rien :
    fit_to_budget tronque en dernier recours, donc c'est vrai par construction.
    """
    from to8sfx import codegen

    worst = {}
    for cat in design.CATEGORIES:
        truncated = 0
        peak = 0
        for seed in range(200):
            p = design.randomize(cat, seed=seed)
            frames, noise = design.render(p)
            cmds, _, info = codegen.fit_to_budget(
                frames, noise=noise, channel=4,
                noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
            peak = max(peak, len(cmds))
            truncated += bool(info["truncated"])
        worst[cat] = (truncated, peak)
        assert truncated == 0, f"{cat} : {truncated}/200 tirages tronques"
    print("  " + ", ".join(f"{c} max {p} cmd" for c, (_, p) in worst.items()))


def test_arp_steps_are_locked_and_bounded():
    """Les marches d'arpege sont un tuple, pas un scalaire : ni BOUNDS ni le
    clamp numerique ne les couvrent. Il faut donc verifier a part que le cadenas
    les protege et que la mutation ne les fait pas deriver.

    Le test des cadenas ne pouvait pas le voir : il mute "explosion", dont
    arp_steps vaut (), donc la branche n'y est jamais executee.
    """
    base = design.randomize("ramassage", seed=5)
    assert base.arp_steps, "la categorie ramassage doit fixer des marches"

    verrouille = design.mutate(base, amount=1.0, locked={"arp_steps"}, seed=1)
    assert verrouille.arp_steps == base.arp_steps, "le cadenas n'a pas tenu"

    # une longue chaine de mutations, c'est exactement ce que fait l'utilisateur
    p = base
    for k in range(200):
        p = design.mutate(p, amount=1.0, locked=set(), seed=k)
        for s in p.arp_steps:
            assert design.ARP_STEP_MIN <= s <= design.ARP_STEP_MAX, (
                f"marche {s} hors domaine apres {k + 1} mutations")
    print(f"  200 mutations enchainees, marches restees dans "
          f"[{design.ARP_STEP_MIN}, {design.ARP_STEP_MAX}] : {p.arp_steps}")


def test_randomize_stays_inside_the_category_ranges():
    """Une categorie est un a priori : si ses plages ne sont pas respectees,
    "tir" et "explosion" tirent dans le meme espace et le choix de categorie ne
    sert plus a rien. Les bornes globales, elles, ne le detecteraient pas.
    """
    for nom, cat in design.CATEGORIES.items():
        for seed in range(50):
            p = design.randomize(nom, seed=seed)
            for key, (lo, hi) in cat.get("ranges", {}).items():
                if key in cat.get("fixed", {}):
                    continue  # `fixed` ecrase le tirage, c'est voulu
                v = getattr(p, key)
                assert lo <= v <= hi, (
                    f"{nom} : {key} = {v} hors de sa plage [{lo}, {hi}]")
            for key, want in cat.get("fixed", {}).items():
                assert getattr(p, key) == want, f"{nom} : {key} non fixe"
    print(f"  {len(design.CATEGORIES)} categories, plages et valeurs fixes respectees")


def test_mutate_is_deterministic():
    base = design.randomize("saut", seed=3)
    a = design.mutate(base, amount=0.4, locked={"instrument"}, seed=77)
    b = design.mutate(base, amount=0.4, locked={"instrument"}, seed=77)
    assert a.to_dict() == b.to_dict(), "mutate n'est pas deterministe"
    c = design.mutate(base, amount=0.4, locked={"instrument"}, seed=78)
    assert c.to_dict() != a.to_dict(), "deux graines donnent la meme mutation"
    print("  mutate deterministe a graine donnee")


def test_every_category_fits_the_budget_at_its_worst_corner():
    """L'echantillonnage ne prouve pas la borne : 200 tirages independants sur
    un espace multi-dimensionnel peuvent tres bien n'avoir jamais reuni la pire
    combinaison d'une categorie. On construit donc ce coin a la main.

    Le cout en commandes croit avec la duree, avec le nombre de frappes, et
    quand l'arpege change de marche a chaque trame.
    """
    from to8sfx import codegen

    for nom, cat in design.CATEGORIES.items():
        p = design.randomize(nom, seed=0)
        ranges = cat.get("ranges", {})
        for key in ("attack_frames", "hold_frames", "decay_frames",
                    "noise_hits", "noise_spread_frames"):
            lo, hi = ranges.get(key, design.BOUNDS[key])
            setattr(p, key, design._clamp(key, hi))
        if p.arp_steps:
            p.arp_frames = 1  # une marche par trame : le maximum d'ecritures
        for key, want in cat.get("fixed", {}).items():
            setattr(p, key, want)

        frames, noise = design.render(p)
        cmds, _u, info = codegen.fit_to_budget(
            frames, noise=noise, channel=4,
            noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
        assert not info["truncated"], (
            f"{nom} : tronque a son pire coin ({len(cmds)} commandes, "
            f"{p.duration_frames} trames)")
        print(f"    {nom:12s} pire coin : {len(cmds):3d} commandes")


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
