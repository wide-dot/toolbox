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
