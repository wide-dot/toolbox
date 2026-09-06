"""La banque : deux fichiers assembleur qui doivent rester d'accord.

L'ordre de soundFX.soundTable et celui des `equ` de soundFX.const.asm doivent
coincider. Une divergence ne se voit pas au build : le mauvais son se joue, sans
la moindre erreur. C'est la classe de bug que la banque existe pour supprimer.
"""

import json
import re
import sys

from to8sfx import bank, codegen, design, importer


def _bank():
    b = bank.Bank(name="essai", default_channel=4)
    b.sounds.append(bank.BankSound(name="Laser", category="tir",
                                   params=design.randomize("tir", seed=1)))
    b.sounds.append(bank.BankSound(name="Boum", category="explosion",
                                   params=design.randomize("explosion", seed=2)))
    b.sounds.append(bank.BankSound(name="Piece", category="ramassage",
                                   params=design.randomize("ramassage", seed=3),
                                   channel=2))
    return b


def test_table_and_constants_agree():
    out = _bank().build()
    table = re.findall(r"fdb\s+soundFX\.(\w+)\.data", out["asm"])
    consts = re.findall(r"soundFX\.(\w+)\s+equ\s+(\d+)", out["const"])
    assert table == ["Laser", "Boum", "Piece"], table
    assert consts == [("Laser", "0"), ("Boum", "1"), ("Piece", "2")], consts
    print(f"  table {table} et constantes d'accord")


def test_blocks_round_trip_through_the_parser():
    """Relire ce qu'on vient d'ecrire : les tailles et la voie doivent coller."""
    b = _bank()
    out = b.build()
    for entry in out["per_sound"]:
        channel, cmds = importer.parse_asm_sound(out["asm"],
                                                 f"soundFX.{entry['name']}.data")
        assert channel == entry["channel"], (
            f"{entry['name']} : voie {channel} relue, {entry['channel']} ecrite")
        assert len(cmds) == entry["commands"], (
            f"{entry['name']} : {len(cmds)} commandes relues, "
            f"{entry['commands']} annoncees")
    print(f"  {len(out['per_sound'])} blocs relus, tailles et voies conformes")


def test_per_sound_channel_overrides_the_default():
    out = _bank().build()
    by_name = {e["name"]: e for e in out["per_sound"]}
    assert by_name["Laser"]["channel"] == 4, "la voie par defaut n'est pas prise"
    assert by_name["Piece"]["channel"] == 2, "la surcharge par son n'est pas prise"
    print("  voie par defaut 4, surcharge a 2 sur un son")


def test_noise_layer_refuses_a_channel_above_six():
    b = bank.Bank(default_channel=8)
    p = design.randomize("explosion", seed=5)
    p.noise_on = True
    b.sounds.append(bank.BankSound(name="Boum", category="explosion", params=p))
    try:
        b.build()
    except ValueError as exc:
        assert "voie" in str(exc).lower()
        print("  couche bruit refusee sur la voie 8")
        return
    raise AssertionError("voie 8 acceptee avec la couche bruit")


def test_duplicate_names_are_refused():
    b = _bank()
    b.sounds.append(bank.BankSound(name="Laser", category="tir",
                                   params=design.randomize("tir", seed=9)))
    try:
        b.build()
    except ValueError as exc:
        assert "Laser" in str(exc)
        print("  nom en double refuse")
        return
    raise AssertionError("nom en double accepte : deux equ pour deux ids")


def test_json_round_trip():
    b = _bank()
    again = bank.Bank.from_json(b.to_json())
    assert again.name == b.name
    assert again.default_channel == b.default_channel
    assert len(again.sounds) == len(b.sounds)
    for avant, apres in zip(b.sounds, again.sounds):
        # Tous les champs, pas seulement le nom : une surcharge de voie perdue
        # au rechargement serait remplacee en silence par la voie par defaut,
        # et le son sortirait sur la mauvaise voie sans que rien ne le dise.
        assert apres.name == avant.name
        assert apres.channel == avant.channel, (
            f"{avant.name} : voie {apres.channel} relue, {avant.channel} ecrite")
        assert apres.priority == avant.priority
        assert apres.category == avant.category
        assert apres.params.to_dict() == avant.params.to_dict()
    print(f"  {len(again.sounds)} sons, tous les champs conserves")


def test_from_json_rejects_arp_steps_out_of_bounds():
    """Une banque ecrite avant le garde-fou de mutate peut porter des marches
    hors du domaine -24..+24 (voir design.ARP_STEP_MIN/MAX). Bank.from_json
    doit le refuser au lieu de fabriquer un son que design.render ferait
    deraper en silence."""
    b = _bank()
    d = json.loads(b.to_json())
    d["sounds"][0]["params"]["arp_steps"] = [0, 999, -999]
    try:
        bank.Bank.from_json(json.dumps(d))
    except ValueError as exc:
        msg = str(exc).lower()
        assert "arpege" in msg or "arp_steps" in msg
        assert "999" in str(exc)
        print("  marche d'arpege hors domaine refusee au chargement")
        return
    raise AssertionError("marches d'arpege hors domaine acceptees en silence")


def test_noise_sound_carries_its_warning_in_the_asm():
    """Un bruitage qui bascule la puce en mode rythme requisitionne les voies 6
    a 8. Si la musique du jeu s'en sert, son etat de batterie est ecrase. Cet
    avertissement doit voyager avec le code genere, pas rester dans l'interface.
    """
    b = bank.Bank(default_channel=4)          # voie valide, contrairement au
    p = design.randomize("explosion", seed=5)  # test qui verifie le refus
    p.noise_on = True
    b.sounds.append(bank.BankSound(name="Boum", category="explosion", params=p))
    out = b.build()
    assert "ATTENTION" in out["asm"], "l'avertissement n'est pas dans l'assembleur"
    assert "rythme" in out["asm"].lower()
    print("  avertissement de couche bruit present dans le bloc genere")


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
