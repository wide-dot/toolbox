"""La sous-commande `vgm` de la ligne de commande.

On passe par le vrai parseur d'arguments, pas par un faux objet args : la moitie
des erreurs de CLI sont des noms d'option qui ne correspondent pas a ce que la
fonction lit (`--from-frame` vs `args.from_frame`), et un faux args ne les
attrape pas.
"""

import io
import os
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

from to8sfx import codegen, importer

from tests.test_vgm import END, note_on, vgm_bytes, w, wait50

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "cli.py")


def _load_cli():
    """Importe cli.py, qui n'est pas dans un paquet."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("to8sfx_cli", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vgm_file(body: bytes = None) -> str:
    if body is None:
        body = (note_on(ch=1, inst=5) + wait50(10) + w(0x11, 0x66)
                + wait50(10) + note_on(ch=3, inst=7) + wait50(5) + END)
    fh = tempfile.NamedTemporaryFile(suffix=".vgm", delete=False)
    fh.write(vgm_bytes(body))
    fh.close()
    return fh.name


class CliExit(Exception):
    """Un sys.exit() de la CLI, converti en exception ordinaire.

    SystemExit herite de BaseException, pas de Exception : laisse passer, il
    traverse le `except AssertionError` du lanceur de tests et arrete TOUTE la
    suite au lieu de faire echouer un test. On le convertit donc ici.
    """

    def __init__(self, code, sortie: str, erreur: str):
        super().__init__(f"{code} :: {erreur or sortie}")
        self.code = code
        self.sortie = sortie
        self.erreur = erreur


def _run(argv: list[str]) -> tuple[str, str]:
    """Lance la CLI avec `argv` et rend (stdout, stderr)."""
    cli = _load_cli()
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["cli.py"] + argv
    try:
        with redirect_stdout(out), redirect_stderr(err):
            cli.main()
    except SystemExit as e:
        raise CliExit(e.code, out.getvalue(), err.getvalue()) from None
    finally:
        sys.argv = old
    return out.getvalue(), err.getvalue()


def test_survey_lists_the_channels_without_writing_anything():
    """`--survey` doit servir de premiere etape : on regarde ce que le fichier
    contient avant de choisir une voie."""
    src = _vgm_file()
    try:
        out, err = _run(["vgm", src, "--survey"])
    finally:
        os.unlink(src)
    texte = out + err
    assert "voie 1" in texte and "voie 3" in texte, texte
    assert "Clarinet" in texte, texte
    assert "fcb" not in texte, "l'inventaire ne doit rien generer"
    print(f"  inventaire imprime : {len(texte.splitlines())} ligne(s)")


def test_the_subcommand_writes_a_block_for_the_chosen_channel():
    src = _vgm_file()
    dst = tempfile.mktemp(suffix=".asm")
    try:
        _run(["vgm", src, "--from-channel", "1", "--name", "Laser",
              "--channel", "4", "-o", dst])
        asm = open(dst).read()
    finally:
        os.unlink(src)
        if os.path.exists(dst):
            os.unlink(dst)
    voie, cmds = importer.parse_asm_sound(asm, "soundFX.Laser.data")
    assert voie == 4, voie
    assert len(cmds) >= 3, len(cmds)
    print(f"  bloc ecrit et relu : voie {voie}, {len(cmds)} commandes")


def test_the_window_options_shorten_the_block():
    """On compare deux fenetres du MEME fichier : une assertion sur la seule
    fenetre courte passerait quelle que soit la valeur de --to-frame.

    La duree se lit dans l'en-tete de commentaire et non dans les delais relus :
    `to_asm` omet volontairement le dernier octet de delai, que le driver ne lit
    jamais (il s'arrete sur le compteur de commandes avant), donc un aller-retour
    par l'assembleur perd toujours le dernier delai.
    """
    src = _vgm_file()
    courts, longs = tempfile.mktemp(suffix=".asm"), tempfile.mktemp(suffix=".asm")
    try:
        _run(["vgm", src, "--from-channel", "1", "--name", "Court",
              "--from-frame", "0", "--to-frame", "5", "-o", courts])
        _run(["vgm", src, "--from-channel", "1", "--name", "Long",
              "--from-frame", "0", "--to-frame", "25", "-o", longs])
        a, b = open(courts).read(), open(longs).read()
    finally:
        for f in (src, courts, longs):
            if os.path.exists(f):
                os.unlink(f)

    def duree(asm):
        m = re.search(r"; \d+ commandes, \d+ octets, ([\d.]+) s", asm)
        assert m, f"duree absente de l'en-tete :\n{asm[:200]}"
        return float(m.group(1))

    assert duree(a) == 0.10, duree(a)   # 5 trames de 20 ms
    assert duree(b) == 0.50, duree(b)   # 25 trames
    # et la fenetre courte porte bien moins de commandes ou autant, jamais plus
    _v1, c1 = importer.parse_asm_sound(a, "soundFX.Court.data")
    _v2, c2 = importer.parse_asm_sound(b, "soundFX.Long.data")
    assert len(c1) <= len(c2), (len(c1), len(c2))
    print(f"  fenetre 0-5 : {duree(a):.2f} s / {len(c1)} cmd ; "
          f"0-25 : {duree(b):.2f} s / {len(c2)} cmd")


def test_a_preview_wav_can_be_written():
    src = _vgm_file()
    dst, wav = tempfile.mktemp(suffix=".asm"), tempfile.mktemp(suffix=".wav")
    try:
        _run(["vgm", src, "--from-channel", "1", "--name", "Laser", "-o", dst,
              "--wav", wav])
        assert os.path.exists(wav), "aucun wav ecrit"
        taille = os.path.getsize(wav)
        assert taille > 1000, taille
    finally:
        for f in (src, dst, wav):
            if os.path.exists(f):
                os.unlink(f)
    print(f"  preview ecrit : {taille} octets")


def test_a_vgm_without_ym2413_fails_with_a_useful_message():
    fh = tempfile.NamedTemporaryFile(suffix=".vgm", delete=False)
    fh.write(vgm_bytes(wait50(1) + END, ym2413=0, sn76489=3579545))
    fh.close()
    try:
        _run(["vgm", fh.name, "--survey"])
    except CliExit as e:
        assert "SN76489" in str(e), e
        print(f"  echec explicite : {str(e)[:70]}...")
        return
    finally:
        os.unlink(fh.name)
    raise AssertionError("un VGM sans YM2413 a ete accepte")


def test_a_channel_absent_from_the_file_fails_clearly():
    src = _vgm_file()
    try:
        _run(["vgm", src, "--from-channel", "8", "--name", "X"])
    except CliExit as e:
        assert "voie 8" in str(e), e
        print(f"  voie absente signalee : {str(e)[:70]}...")
        return
    finally:
        os.unlink(src)
    raise AssertionError("une voie sans ecriture a ete acceptee")
