"""Relecture de donnees soundFX existantes.

Sert a deux choses : reprendre un bruitage deja ecrit a la main pour le
retoucher, et surtout valider le generateur en rejouant les sons de r-type,
dont on sait qu'ils marchent sur la machine.
"""

from __future__ import annotations

import io
import re
import wave

import numpy as np

from .codegen import CMD_CUSTOM_PATCH, Command

_FCB = re.compile(r"^\s*fcb\s+(.+?)\s*(?:;.*)?$", re.IGNORECASE)
_LABEL = re.compile(r"^([A-Za-z_.][\w.]*)\s*$")


def _value(tok: str) -> int:
    tok = tok.strip()
    if tok.startswith("$"):
        return int(tok[1:], 16)
    if tok.startswith("%"):
        return int(tok[1:], 2)
    return int(tok, 10)


def parse_asm_sound(text: str, label: str) -> tuple[int, list[Command]]:
    """Extrait (voie, commandes) du bloc `label` d'un source assembleur.

    Le dernier octet de delai est optionnel dans le format (le driver s'arrete
    sur le compteur de commandes avant de le lire) : on le tolere absent.
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        m = _LABEL.match(ln)
        if m and m.group(1) == label:
            start = i + 1
            break
    if start is None:
        raise KeyError(f"label introuvable : {label}")

    data: list[int] = []
    for ln in lines[start:]:
        if _LABEL.match(ln) and ln.strip() != label:
            break  # label suivant : fin du bloc
        m = _FCB.match(ln)
        if not m:
            continue
        for tok in m.group(1).split(","):
            if tok.strip():
                data.append(_value(tok))

    if len(data) < 2:
        raise ValueError(f"{label} : donnees trop courtes")

    n_cmds, channel = data[0], data[1]
    body = data[2:]
    cmds: list[Command] = []
    pos = 0
    for _ in range(n_cmds):
        if pos >= len(body):
            break
        reg = body[pos]
        if reg == CMD_CUSTOM_PATCH:
            addr = (body[pos + 1] << 8) | body[pos + 2] if pos + 2 < len(body) else 0
            cmds.append(Command(CMD_CUSTOM_PATCH, addr, 0))
            pos += 3
            continue
        val = body[pos + 1] if pos + 1 < len(body) else 0
        delay = body[pos + 2] if pos + 2 < len(body) else 0  # dernier delai omis
        cmds.append(Command(reg, val, delay))
        pos += 3
    return channel, cmds


def write_wav(path_or_buf, x: np.ndarray, rate: int = 44100, gain: float = 8.0):
    """Ecrit un mono 16 bits.

    gain fixe (et non normalisation par son) : on veut que deux bruitages
    gardent entre eux le meme rapport de niveau qu'ils auront dans le jeu. Une
    voie seule ne represente qu'un neuvieme du plein de la puce, d'ou le x8.
    """
    y = np.clip(x * gain, -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2").tobytes()
    if isinstance(path_or_buf, (str, bytes)):
        wf = wave.open(path_or_buf, "wb")
    else:
        wf = wave.open(path_or_buf, "wb")
    with wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def wav_bytes(x: np.ndarray, rate: int = 44100, gain: float = 8.0) -> bytes:
    buf = io.BytesIO()
    write_wav(buf, x, rate, gain)
    return buf.getvalue()
