"""Section rythme du YM2413 : la seule source de BRUIT de la puce.

La voie melodique ne sait produire que des sons periodiques ; c'est pourquoi
une explosion enregistree ne se convertit pas. Le registre $0E bascule la puce
en mode rythme : les voies 6, 7 et 8 deviennent cinq percussions, dont la
caisse claire et la charleston sont a base de bruit. Platitude spectrale
mesuree sur l'emulateur : 0,27 et 0,12, contre 0,00 pour une note melodique.

Adressage : le driver ecrit les registres <= $0F tels quels et AJOUTE le numero
de voie aux autres. Les registres des voies rythmiques etant au-dessus de $0F,
il faut emettre `reg - voie` pour que la puce recoive `reg`. A partir de la
voie 7, $16 - 7 = $0F retomberait dans la plage ecrite verbatim et viserait le
registre de controle du rythme : la couche est alors refusee.
"""

from __future__ import annotations

from .opll import REG_RHYTHM, freq_to_fnum_block

RHYTHM_ON = 0x20  # bit 5 de $0E : bascule en mode rythme

# Masques de declenchement, bits 0 a 4 de $0E.
HITS: dict[str, int] = {
    "BD": 0x10,   # grosse caisse (voie 6)
    "SD": 0x08,   # caisse claire (voie 7)
    "TOM": 0x04,  # tom          (voie 8)
    "CYM": 0x02,  # cymbale      (voie 8)
    "HH": 0x01,   # charleston   (voie 7)
}
KIT_ORDER: tuple[str, ...] = ("BD", "SD", "TOM", "CYM", "HH")

# Voie maximale utilisable avec la couche bruit : au-dela, la
# pre-soustraction retombe sous $0F. Voir l'en-tete du module.
MAX_CHANNEL = 6

# Hauteurs de la grosse caisse et du tom : 16 crans, du plus grave au plus
# aigu. Les percussions rythmiques prennent leur hauteur dans les registres
# de hauteur des voies 6 et 8 comme une note ordinaire.
_PITCH_HZ = [40.0 * (300.0 / 40.0) ** (i / 15.0) for i in range(16)]
PITCH_TABLE = [freq_to_fnum_block(f) for f in _PITCH_HZ]


def check_channel(channel: int) -> None:
    """Leve ValueError si la couche bruit ne peut pas viser juste sur cette voie."""
    if not 0 <= channel <= MAX_CHANNEL:
        raise ValueError(
            f"couche bruit impossible sur la voie {channel} : les registres de "
            f"la section rythme recoivent le numero de voie, et au-dela de la "
            f"voie {MAX_CHANNEL} la compensation retombe sous $0F. "
            f"Choisir une voie de 0 a {MAX_CHANNEL}, ou couper la couche bruit."
        )


def encode(reg: int, channel: int) -> int:
    """Registre a EMETTRE pour que la puce recoive `reg`."""
    if reg <= 0x0F:
        return reg
    check_channel(channel)
    return reg - channel


def arm_writes(noise_pitch: int, noise_vol: int) -> list[tuple[int, int]]:
    """Les ecritures qui arment la section rythme, en registres ABSOLUS.

    La documentation du YM2413 fixe le volume des percussions dans les quartets
    des registres $36-$38 ; la hauteur de la grosse caisse et du tom se regle
    comme celle d'une note.
    """
    pitch = max(0, min(15, int(noise_pitch)))
    vol = max(0, min(15, int(noise_vol)))
    fnum, block = PITCH_TABLE[pitch]
    lo = fnum & 0xFF
    hi = ((fnum >> 8) & 1) | ((block & 7) << 1)

    return [
        (0x16, lo), (0x26, hi), (0x36, (vol << 4) | vol),   # voie 6 : grosse caisse
        (0x17, 0x50), (0x27, 0x05), (0x37, (vol << 4) | vol),  # voie 7 : charleston + caisse claire
        (0x18, lo), (0x28, hi), (0x38, (vol << 4) | vol),   # voie 8 : tom + cymbale
    ]


def mask_of(names) -> int:
    """Masque de declenchement pour un ensemble de percussions."""
    m = 0
    for n in names:
        m |= HITS.get(n, 0)
    return m


__all__ = ["RHYTHM_ON", "HITS", "KIT_ORDER", "MAX_CHANNEL", "PITCH_TABLE",
           "REG_RHYTHM", "check_channel", "encode", "arm_writes", "mask_of"]
