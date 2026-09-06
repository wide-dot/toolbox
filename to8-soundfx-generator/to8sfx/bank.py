"""La banque de bruitages, et les deux fichiers assembleur qu'elle produit.

soundFX.asm porte la table et les blocs de donnees ; soundFX.const.asm porte
les identifiants. L'ordre de la table et celui des `equ` DOIVENT coincider :
une divergence ne se voit pas au build, elle joue simplement le mauvais son.
Les tenir a la main est une source de bug silencieux ; c'est la raison d'etre
de ce module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import codegen, design, rhythm

NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


@dataclass
class BankSound:
    name: str
    params: design.SfxParams
    category: str = ""
    channel: int | None = None  # None = voie par defaut de la banque
    priority: int = 1


@dataclass
class Bank:
    name: str = "banque"
    default_channel: int = 4
    sounds: list[BankSound] = field(default_factory=list)

    def channel_of(self, s: BankSound) -> int:
        return self.default_channel if s.channel is None else int(s.channel)

    # --- serialisation ---

    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "default_channel": self.default_channel,
            "sounds": [{"name": s.name, "category": s.category,
                        "channel": s.channel, "priority": s.priority,
                        "params": s.params.to_dict()} for s in self.sounds],
        }, indent=2)

    @staticmethod
    def from_json(text: str) -> "Bank":
        d = json.loads(text)
        b = Bank(name=d.get("name", "banque"),
                 default_channel=int(d.get("default_channel", 4)))
        for s in d.get("sounds", []):
            params = design.SfxParams.from_dict(s.get("params", {}))
            _check_arp_steps(s.get("name", "?"), params.arp_steps)
            b.sounds.append(BankSound(
                name=s["name"],
                params=params,
                category=s.get("category", ""),
                channel=s.get("channel"),
                priority=int(s.get("priority", 1)),
            ))
        return b

    # --- generation ---

    def _validate(self) -> None:
        seen = set()
        for s in self.sounds:
            if not s.name or any(c not in NAME_OK for c in s.name):
                raise ValueError(
                    f"nom de son invalide : {s.name!r}. Il devient une etiquette "
                    "assembleur, donc lettres, chiffres et souligne seulement.")
            if s.name in seen:
                raise ValueError(
                    f"nom en double : {s.name}. Deux `equ` porteraient le meme "
                    "nom pour deux identifiants differents.")
            seen.add(s.name)
            # La voie part dans le deuxieme octet de l'en-tete du bloc : une
            # valeur aberrante s'y ecrivait telle quelle jusqu'a la machine.
            rhythm.check_any_channel(self.channel_of(s))
            if s.params.noise_on:
                rhythm.check_channel(self.channel_of(s))

    def build(self) -> dict:
        """Produit les deux fichiers et le detail par son."""
        self._validate()

        blocks: list[str] = []
        per_sound: list[dict] = []
        warnings: list[str] = []
        total = 0

        for i, s in enumerate(self.sounds):
            channel = self.channel_of(s)
            frames, noise = design.render(s.params)
            cmds, _used, info = codegen.fit_to_budget(
                frames, noise=noise, channel=channel,
                noise_pitch=s.params.noise_pitch, noise_vol=s.params.noise_vol,
                quantize_pitch=True)
            st = codegen.stats(cmds)
            total += st["bytes"]

            source = f"{s.category or 'creation'}, graine {s.params.seed}"
            block = codegen.to_asm(s.name, channel, cmds, priority=s.priority,
                                   source=source)
            if s.params.noise_on:
                avant = block
                block = block.replace(
                    f"; {s.name} - genere par to8-soundfx-generator",
                    f"; {s.name} - genere par to8-soundfx-generator\n"
                    ";\n"
                    "; ATTENTION : ce son utilise la section RYTHME du YM2413.\n"
                    "; Le registre $0E requisitionne les voies 6, 7 et 8 de la\n"
                    "; puce. Si la musique du jeu s'en sert, son etat de batterie\n"
                    "; sera ecrase pendant la duree du bruitage.", 1)
                if block == avant:
                    # str.replace() qui ne trouve rien rend la chaine inchangee,
                    # sans la moindre erreur : sans ce garde-fou, un changement
                    # de format dans codegen.to_asm ferait disparaitre
                    # l'avertissement en silence, et l'utilisateur livrerait un
                    # bruitage qui ecrase la batterie de la musique sans le savoir.
                    raise RuntimeError(
                        f"{s.name} : l'avertissement de couche bruit n'a pas pu etre "
                        "insere - le format d'en-tete de codegen.to_asm a change. "
                        "Sans lui, un bruitage qui requisitionne les voies 6 a 8 "
                        "serait livre sans prevenir qu'il ecrase la batterie de la "
                        "musique.")
            blocks.append(block)

            if info["truncated"]:
                warnings.append(
                    f"{s.name} : TRONQUE, il depasse 255 commandes meme simplifie "
                    "au maximum. Raccourcir la chute.")
            per_sound.append({
                "index": i, "name": s.name, "channel": channel,
                "priority": s.priority, "category": s.category,
                "commands": st["commands"], "bytes": st["bytes"],
                "seconds": round(st["seconds"], 2), "truncated": info["truncated"],
            })

        head = [
            f"; Banque {self.name} - genere par to8-soundfx-generator",
            f"; {len(self.sounds)} son(s), {total} octets de donnees",
            ";",
            "; L'ordre de cette table EST l'ordre des identifiants de",
            "; soundFX.const.asm. Ne pas reordonner l'un sans l'autre.",
            "",
            "soundFX.soundTable",
        ]
        for i, s in enumerate(self.sounds):
            head.append(f"            fdb     soundFX.{s.name}.data"
                        f"{' ' * max(1, 24 - len(s.name))}; {i} - "
                        f"{s.category or 'creation'}, voie {self.channel_of(s)}")
        asm = "\n".join(head) + "\n\n" + "\n".join(blocks)

        const = [
            f"; Identifiants de la banque {self.name}",
            "; Meme ordre que soundFX.soundTable.",
            "",
        ]
        for i, s in enumerate(self.sounds):
            const.append(f"soundFX.{s.name}{' ' * max(1, 24 - len(s.name))}equ {i}")
        return {
            "asm": asm,
            "const": "\n".join(const) + "\n",
            "bytes": total,
            "per_sound": per_sound,
            "warnings": warnings,
        }


def _check_arp_steps(sound_name: str, arp_steps: tuple[int, ...]) -> None:
    """Refuse une marche d'arpege hors domaine des l'entree JSON.

    mutate() borne arp_steps depuis sa correction, mais SfxParams.from_dict
    ne valide rien : une banque ecrite avant ce garde-fou (ou modifiee a la
    main) peut porter des marches hors de -24..+24. Ce module lit du JSON
    venu de n'importe ou, donc c'est ici, a la frontiere, qu'il faut arreter
    la valeur avant qu'elle n'atteigne design.render en silence.
    """
    hors_domaine = [v for v in arp_steps
                    if not (design.ARP_STEP_MIN <= v <= design.ARP_STEP_MAX)]
    if hors_domaine:
        raise ValueError(
            f"{sound_name} : marche(s) d'arpege hors domaine {hors_domaine} "
            f"(attendu {design.ARP_STEP_MIN}..{design.ARP_STEP_MAX} demi-tons). "
            "Cette banque a sans doute ete ecrite avant le garde-fou de mutate : "
            "corriger arp_steps a la main dans le JSON, ou regenerer le son "
            "avec design.randomize/design.mutate."
        )
