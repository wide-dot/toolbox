"""Les endpoints de creation, appeles en direct (sans reseau).

On instancie le serveur pour de vrai serait plus lourd que necessaire : les
fonctions de traitement sont testables telles quelles, et c'est la ou vit la
logique.
"""

import sys

from to8sfx import bank, design, server


def test_render_design_returns_everything_the_ui_needs():
    p = design.randomize("tir", seed=11)
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Laser", "priority": 1})
    for key in ("asm", "stats", "curves", "preview", "warnings", "params"):
        assert key in out, f"cle absente de la reponse : {key}"
    assert out["stats"]["commands"] > 0
    assert len(out["curves"]["freq"]) == p.duration_frames
    assert "soundFX.Laser.data" in out["asm"]
    print(f"  {out['stats']['commands']} commandes, {out['stats']['bytes']} octets")


def test_noise_layer_warns_about_the_music():
    p = design.randomize("explosion", seed=4)
    p.noise_on = True
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Boum", "priority": 1})
    joined = " ".join(out["warnings"]).lower()
    assert "rythme" in joined and ("6" in joined or "musique" in joined), out["warnings"]
    print("  avertissement de la couche bruit present")


def test_variants_endpoint_returns_playable_mutations():
    """L'endpoint des variantes est la moitie de la boucle de creation : on
    mute, on ecoute, on adopte. Sans test, une regression sur tout cet endpoint
    passerait inapercue.
    """
    p = design.randomize("tir", seed=21)
    out = server._variants({"params": p.to_dict(), "amount": 0.3,
                            "locked": ["instrument"], "seed": 5,
                            "count": 8, "channel": 4})
    variants = out["variants"]
    assert variants, "aucune variante produite"
    assert len(variants) <= 8
    for v in variants:
        assert v["stats"]["commands"] > 0
        assert v["preview"].startswith("/api/variant.wav?i=")
        assert v["params"]["instrument"] == p.instrument, "le cadenas n'a pas tenu"
    assert len(server.STATE["variant_wavs"]) == len(variants), (
        "un wav de preview par variante, sinon les indices ne correspondent plus")
    print(f"  {len(variants)} variantes, cadenas tenu, wavs alignes")


def test_variants_skip_what_the_noise_layer_forbids():
    """Une variante dont la voie est incompatible avec la couche bruit est
    ecartee en silence. Ce comportement est voulu, mais il doit etre verifie :
    une branche qui jette des choses sans rien dire est celle qu'on veut voir
    testee.
    """
    p = design.randomize("explosion", seed=9)
    p.noise_on = True
    out = server._variants({"params": p.to_dict(), "amount": 0.3, "locked": [],
                            "seed": 1, "count": 4, "channel": 8})  # voie interdite
    assert out["variants"] == [], (
        "des variantes sont passees alors que la voie 8 est incompatible avec "
        "le mode rythme")
    print("  variantes ecartees sur une voie interdite")


def test_bank_endpoints_keep_state():
    server.STATE["bank"] = bank.Bank(default_channel=4)
    p = design.randomize("tir", seed=2)
    server._bank_add({"name": "Laser", "category": "tir", "params": p.to_dict()})
    server._bank_add({"name": "Boum", "category": "explosion",
                      "params": design.randomize("explosion", seed=3).to_dict()})
    view = server._bank_view()
    assert len(view["sounds"]) == 2, view["sounds"]
    assert view["build"]["bytes"] > 0
    server._bank_remove({"index": 0})
    view = server._bank_view()
    assert [s["name"] for s in view["sounds"]] == ["Boum"], view["sounds"]
    print(f"  banque : ajout, vue, retrait ; {view['build']['bytes']} octets")


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
