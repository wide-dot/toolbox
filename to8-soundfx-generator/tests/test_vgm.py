"""Relecture d'un export VGM (DefleMask) vers le flux de commandes du driver.

Le VGM porte les ecritures de registres elles-memes : rien a deviner, ni
hauteur a detecter ni timbre a apparier. Tout l'enjeu est ailleurs, et il est
entierement dans les conversions :

- le VGM compte le temps en samples a 44100 Hz, le driver en ticks de 20 ms ;
- le VGM nomme la voie dans le registre ($12 = voie 2), le driver AJOUTE la
  voie de sortie au registre qu'on lui donne ;
- le VGM a nef voies, le driver une seule.

Une erreur dans l'une de ces trois conversions ne fait pas planter : elle
produit un bruitage qui joue, faux. D'ou les tests d'aller-retour et de duree.
"""

import gzip
import os
import struct

from to8sfx import codegen, importer, opll, vgm

CH = 1  # voie source employee par la plupart des cas
OUT = 4  # voie de sortie du driver


# --- Construction de VGM de test -------------------------------------------
#
# On fabrique les fichiers ici plutot que d'en versionner : un cas de test doit
# pouvoir se lire en entier, et les fichiers du depot sont des musiques de 20 Ko
# dont on ne controle pas le contenu.


def vgm_bytes(body: bytes, version: int = 0x150, ym2413: int = opll.YM2413_CLOCK,
              sn76489: int = 0, data_at: int = 0x40) -> bytes:
    """En-tete VGM minimal + `body`, les donnees commencant a `data_at`."""
    head = bytearray(data_at)
    head[0x00:0x04] = b"Vgm "
    struct.pack_into("<I", head, 0x04, data_at + len(body) - 4)  # fin de fichier
    struct.pack_into("<I", head, 0x08, version)
    struct.pack_into("<I", head, 0x0C, sn76489)
    struct.pack_into("<I", head, 0x10, ym2413)
    if version >= 0x150:
        struct.pack_into("<I", head, 0x34, data_at - 0x34)
    return bytes(head) + body


def w(reg: int, val: int) -> bytes:
    """Ecriture YM2413 (opcode $51)."""
    return bytes([0x51, reg, val])


def wait50(n: int = 1) -> bytes:
    """n attentes de 882 samples : l'export PAL de DefleMask."""
    return bytes([0x63]) * n


def wait60(n: int = 1) -> bytes:
    """n attentes de 735 samples : l'export NTSC de DefleMask."""
    return bytes([0x62]) * n


def wait(samples: int) -> bytes:
    return bytes([0x61]) + struct.pack("<H", samples)


END = bytes([0x66])


def note_on(ch: int = CH, inst: int = 5, vol: int = 0,
            fnum: int = 0x155, block: int = 4) -> bytes:
    """Les trois ecritures d'un debut de note, dans l'ordre du driver."""
    return (w(0x30 + ch, (inst << 4) | vol)
            + w(0x10 + ch, fnum & 0xFF)
            + w(0x20 + ch, ((fnum >> 8) & 1) | ((block & 7) << 1) | opll.KEY_ON))


def regs_of(cmds) -> list[tuple[int, int]]:
    return [(c.reg, c.data) for c in cmds if c.reg != codegen.CMD_CUSTOM_PATCH]


# --- En-tete ----------------------------------------------------------------


def test_a_v150_header_puts_the_data_at_0x40():
    v = vgm.parse(vgm_bytes(w(0x11, 0x55) + wait50(1) + END, version=0x150))
    assert v.writes == [(0, 0x11, 0x55)], v.writes
    assert v.clock == opll.YM2413_CLOCK
    print(f"  v1.50 : donnees a $40, {len(v.writes)} ecriture(s)")


def test_a_v161_header_follows_the_data_offset():
    """Les VGM du depot sont en v1.61, donnees a $100 : lues a $40 on tomberait
    dans le rembourrage de l'en-tete et on interpreterait des zeros."""
    v = vgm.parse(vgm_bytes(w(0x11, 0x55) + wait50(1) + END,
                            version=0x161, data_at=0x100))
    assert v.writes == [(0, 0x11, 0x55)], v.writes
    print("  v1.61 : donnees a $100, decalage suivi")


def test_a_gzipped_vgz_is_accepted():
    brut = vgm_bytes(w(0x11, 0x55) + wait50(1) + END)
    v = vgm.parse(gzip.compress(brut))
    assert v.writes == [(0, 0x11, 0x55)], v.writes
    print("  .vgz decompresse")


def test_a_vgm_without_ym2413_names_the_chip_it_carries():
    """Le cas reel est un export SN76489 (music/TO-001.vgm) ou YM2612. Le
    message doit dire quoi changer dans DefleMask, pas seulement que c'est
    refuse."""
    data = vgm_bytes(wait50(1) + END, ym2413=0, sn76489=opll.YM2413_CLOCK)
    try:
        vgm.parse(data)
    except ValueError as e:
        assert "SN76489" in str(e), f"le message ne nomme pas la puce : {e}"
        print(f"  refus explicite : {e}")
        return
    raise AssertionError("un VGM sans YM2413 a ete accepte")


def test_an_unknown_opcode_names_its_position():
    """Sauter un opcode inconnu en silence desynchroniserait tout le flux qui
    suit : les donnees seraient lues comme des opcodes."""
    data = vgm_bytes(w(0x11, 0x55) + bytes([0x2A]) + END)
    try:
        vgm.parse(data)
    except ValueError as e:
        assert "2a" in str(e).lower(), f"la position n'est pas nommee : {e}"
        print(f"  opcode inconnu signale : {e}")
        return
    raise AssertionError("un opcode inconnu est passe")


# --- Temps ------------------------------------------------------------------


def test_a_60hz_export_keeps_its_real_duration():
    """DefleMask exporte en 60 Hz si la machine est reglee en NTSC. Compter une
    attente pour un tick etirerait le bruitage de 20 % ; il faut diviser les
    samples par 882."""
    pal = vgm.parse(vgm_bytes(w(0x11, 1) + wait50(50) + w(0x11, 2) + END))
    ntsc = vgm.parse(vgm_bytes(w(0x11, 1) + wait60(50) + w(0x11, 2) + END))
    assert pal.n_ticks == 50, pal.n_ticks
    # 50 x 735 = 36750 samples = 41,66 ticks -> 41
    assert ntsc.n_ticks == 41, ntsc.n_ticks
    print(f"  50 trames PAL -> {pal.n_ticks} ticks ; "
          f"50 trames NTSC -> {ntsc.n_ticks} ticks (meme duree reelle)")


def test_sub_tick_waits_are_carried_not_dropped():
    """Dix attentes de 441 samples font exactement 5 ticks. Arrondir chacune
    separement en donnerait zero : c'est le report du reste qu'on verifie."""
    body = w(0x11, 1) + (wait(441) * 10) + w(0x11, 2) + END
    v = vgm.parse(vgm_bytes(body))
    assert v.n_ticks == 5, v.n_ticks
    assert v.writes[-1][0] == 5, v.writes
    print("  10 x 441 samples = 5 ticks, reste reporte")


# --- Filtrage de voie -------------------------------------------------------


def test_only_the_chosen_channel_survives():
    body = (note_on(ch=0, fnum=0x100) + note_on(ch=1, fnum=0x155)
            + wait50(5) + END)
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, 1, 0, None)
    assert len(cmds) == 3, f"3 ecritures attendues pour la voie 1, {len(cmds)}"
    # $31 = inst 5, vol 0 ; $11 = F-Num bas ; $21 = F-Num b8 | block<<1 | key-on
    assert [c.data for c in cmds] == [0x50, 0x55, 0x19], regs_of(cmds)
    print(f"  voie 1 isolee : {len(cmds)} commandes, voie 0 ecartee")


def test_registers_are_rebased_for_the_driver_to_add_the_channel():
    """Le driver AJOUTE la voie de sortie aux registres > $0F. Un $12 lu sur la
    voie 2 doit partir en $10, sinon la puce recoit $12 + voie."""
    v = vgm.parse(vgm_bytes(note_on(ch=2) + wait50(3) + END))
    cmds, _ = vgm.to_commands(v, 2, 0, None)
    assert [c.reg for c in cmds] == [0x30, 0x10, 0x20], [hex(c.reg) for c in cmds]
    # apres l'addition du driver, on retombe sur les registres de la voie 4
    assert {c.reg + OUT for c in cmds} == {0x34, 0x14, 0x24}
    print("  $32/$12/$22 (voie 2) -> $30/$10/$20 -> $34/$14/$24 (voie 4)")


def test_a_channel_silent_in_the_window_is_reported():
    v = vgm.parse(vgm_bytes(note_on(ch=0) + wait50(5) + END))
    cmds, avis = vgm.to_commands(v, 3, 0, None)
    assert cmds == [], cmds
    assert any("voie 3" in a for a in avis), avis
    print(f"  voie muette signalee : {avis[0]}")


# --- Amorcage ---------------------------------------------------------------


def test_a_window_starting_mid_note_reemits_the_channel_state():
    """C'est le cas normal, pas un cas limite : decouper est l'usage meme de la
    selection. Sans amorcage, la note joue avec l'etat de registres qu'un
    bruitage precedent a laisse dans la puce."""
    body = note_on(ch=CH, inst=5, vol=0, fnum=0x155, block=4) + wait50(10) \
        + w(0x10 + CH, 0x66) + wait50(5) + END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, CH, 5, None)
    # l'etat a t=5 reemis en tete, dans l'ordre du driver : volume, F-Num, block
    assert [c.reg for c in cmds[:3]] == [0x30, 0x10, 0x20], [hex(c.reg) for c in cmds]
    assert [c.data for c in cmds[:3]] == [0x50, 0x55, 0x19], regs_of(cmds)
    assert cmds[0].delay == 0 and cmds[1].delay == 0, "l'amorcage est instantane"
    assert cmds[3].data == 0x66, "l'ecriture de la fenetre suit l'amorcage"
    print("  fenetre a t=5 : etat reemis ($30,$10,$20) puis le flux")


def test_the_priming_ends_with_key_on_so_the_pitch_is_complete():
    """L'ordre est celui de frames_to_commands, et pour la meme raison : le
    key-on doit etre ecrit en dernier."""
    v = vgm.parse(vgm_bytes(note_on() + wait50(10) + END))
    cmds, _ = vgm.to_commands(v, CH, 5, None)
    assert cmds[-1].reg == 0x20 or cmds[2].reg == 0x20, [hex(c.reg) for c in cmds]
    assert cmds[2].data & opll.KEY_ON, "le key-on a disparu de l'amorcage"
    print("  key-on ecrit en dernier dans l'amorcage")


# --- Deduplication et delais ------------------------------------------------


def test_a_value_rewritten_identically_adds_no_command():
    """DefleMask reecrit la hauteur a chaque ligne du tracker, meme inchangee.
    Sans deduplication les 6643 ecritures de la voie 2 d'ingame-YM2413 restent
    6643, pour un budget de 255."""
    body = note_on() + wait50(1)
    for _ in range(20):
        body += w(0x10 + CH, 0x55) + wait50(1)  # meme valeur, 20 fois
    body += END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, CH, 0, None)
    assert len(cmds) == 3, f"3 commandes attendues, {len(cmds)} : {regs_of(cmds)}"
    print(f"  23 ecritures VGM -> {len(cmds)} commandes")


def test_a_delay_over_255_ticks_is_split_without_losing_time():
    """Le champ delai tient sur un octet. On scinde en reecrivant un registre a
    l'identique — inoffensif, et ca repart pour 255 ticks."""
    body = note_on() + wait50(300) + w(0x10 + CH, 0x66) + wait50(2) + END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, CH, 0, None)
    assert all(c.delay <= codegen.MAX_DELAY for c in cmds), \
        [c.delay for c in cmds]
    assert sum(c.delay for c in cmds) == 302, sum(c.delay for c in cmds)
    print(f"  302 ticks repartis sur {len(cmds)} commandes, aucun delai > 255")


def test_the_window_length_is_the_total_delay():
    """stats()['seconds'] doit dire la duree de la fenetre choisie, sinon
    l'affichage du budget ment."""
    v = vgm.parse(vgm_bytes(note_on() + wait50(40) + END))
    cmds, _ = vgm.to_commands(v, CH, 0, 25)
    assert sum(c.delay for c in cmds) == 25, sum(c.delay for c in cmds)
    print(f"  fenetre de 25 ticks -> {codegen.stats(cmds)['seconds']:.2f} s")


# --- Patch custom -----------------------------------------------------------


def test_instrument_zero_brings_the_custom_patch():
    patch = bytes([0x21, 0x11, 0x00, 0x08, 0xF0, 0xF0, 0x0F, 0x0F])
    body = b"".join(w(i, patch[i]) for i in range(8)) \
        + note_on(inst=0, vol=3) + wait50(5) + END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, CH, 0, None)
    assert cmds[0].reg == codegen.CMD_CUSTOM_PATCH, [hex(c.reg) for c in cmds]
    assert cmds[0].patch == patch, cmds[0].patch
    print(f"  instrument 0 -> commande $FF, patch {patch.hex()}")


def test_a_rom_instrument_brings_no_patch():
    body = b"".join(w(i, 0x11) for i in range(8)) + note_on(inst=5) + wait50(3) + END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, CH, 0, None)
    assert all(c.reg != codegen.CMD_CUSTOM_PATCH for c in cmds), \
        "patch emis alors que la voie joue un instrument ROM"
    print("  instrument ROM : pas de commande $FF")


def test_a_patch_changed_mid_window_is_reported():
    """codegen.to_asm n'ecrit qu'UNE etiquette de patch : tous ses fdb pointent
    le premier. Deux patchs produiraient un bloc silencieusement faux."""
    body = b"".join(w(i, 0x11) for i in range(8)) + note_on(inst=0) + wait50(5) \
        + w(0x02, 0x7F) + wait50(5) + END
    v = vgm.parse(vgm_bytes(body))
    _cmds, avis = vgm.to_commands(v, CH, 0, None)
    assert any("patch" in a.lower() for a in avis), avis
    print(f"  patch changeant signale : {[a for a in avis if 'patch' in a.lower()][0]}")


# --- Section rythme ---------------------------------------------------------


def test_rhythm_writes_are_reported_as_ignored():
    body = note_on() + w(0x0E, 0x20) + wait50(2) + w(0x0E, 0x30) + wait50(3) + END
    v = vgm.parse(vgm_bytes(body))
    assert v.has_rhythm
    _cmds, avis = vgm.to_commands(v, CH, 0, None)
    assert any("rythme" in a.lower() for a in avis), avis
    print(f"  rythme signale : {[a for a in avis if 'rythme' in a.lower()][0]}")


def test_a_rhythm_requisitioned_channel_is_reported_as_mute():
    """Le mode rythme requisitionne les voies 6, 7 et 8 : une couche melodique
    posee dessus n'est pas approximative, elle est EFFACEE (cf. rhythm.py)."""
    body = w(0x0E, 0x20) + note_on(ch=7) + wait50(3) + END
    v = vgm.parse(vgm_bytes(body))
    _cmds, avis = vgm.to_commands(v, 7, 0, None)
    assert any("muette" in a.lower() or "requisition" in a.lower() for a in avis), avis
    print(f"  voie 7 sous rythme : {avis[0]}")


# --- Inventaire -------------------------------------------------------------


def test_survey_lists_activity_per_channel():
    body = (note_on(ch=0, inst=5) + wait50(2)
            + note_on(ch=2, inst=7) + wait50(8) + END)
    infos = {i.channel: i for i in vgm.survey(vgm.parse(vgm_bytes(body)))}
    assert set(infos) == {0, 2}, sorted(infos)
    assert infos[0].writes == 3 and infos[2].writes == 3
    assert infos[0].first_tick == 0 and infos[2].first_tick == 2
    assert infos[2].instruments == [7], infos[2].instruments
    assert not infos[2].uses_custom
    print(f"  inventaire : {[(i.channel, i.writes, i.instruments) for i in infos.values()]}")


def test_survey_flags_a_channel_that_needs_the_custom_patch():
    v = vgm.parse(vgm_bytes(note_on(ch=3, inst=0) + wait50(2) + END))
    info = next(i for i in vgm.survey(v) if i.channel == 3)
    assert info.uses_custom, "l'instrument 0 n'est pas signale"
    print("  voie 3 : emploi de l'instrument custom signale")


# --- Trace pour l'affichage -------------------------------------------------


def test_the_trace_follows_pitch_and_key_off():
    v = vgm.parse(vgm_bytes(note_on(fnum=0x155, block=4) + wait50(4)
                            + w(0x20 + CH, 0x08) + wait50(4) + END))
    tr = vgm.trace(v, CH, 0, None)
    assert len(tr) == 8, len(tr)
    assert tr[0]["on"] and tr[0]["hz"] > 0
    assert not tr[5]["on"], tr[5]
    attendu = opll.fnum_block_to_freq(0x155, 4)
    assert abs(tr[0]["hz"] - attendu) < 0.5, (tr[0]["hz"], attendu)
    print(f"  trace : {len(tr)} ticks, note a {tr[0]['hz']:.1f} Hz puis key-off")


# --- Aller-retour -----------------------------------------------------------


def test_asm_round_trips_through_the_importer():
    """Le test qui attrape une erreur de rebasage de registre : ce qu'on ecrit
    doit se relire a l'identique par le chemin deja eprouve d'importer.py."""
    body = note_on(ch=2, inst=5) + wait50(6) + w(0x12, 0x66) + wait50(4) + END
    v = vgm.parse(vgm_bytes(body))
    cmds, _ = vgm.to_commands(v, 2, 0, None)
    asm = codegen.to_asm("TestVgm", OUT, cmds, priority=1, source="test")
    voie, relu = importer.parse_asm_sound(asm, "soundFX.TestVgm.data")
    assert voie == OUT, voie
    assert regs_of(relu) == regs_of(cmds), (regs_of(relu), regs_of(cmds))
    # to_asm omet le dernier octet de delai, parse_asm_sound le tolere absent
    assert [c.delay for c in relu[:-1]] == [c.delay for c in cmds[:-1]], \
        ([c.delay for c in relu], [c.delay for c in cmds])
    print(f"  aller-retour : {len(cmds)} commandes identiques apres relecture")


def test_the_generated_block_is_playable():
    """commands_to_events est le chemin du preview : s'il refuse les commandes
    produites ici, on n'entend rien et on ne sait pas pourquoi."""
    v = vgm.parse(vgm_bytes(note_on() + wait50(10) + END))
    cmds, _ = vgm.to_commands(v, CH, 0, None)
    ev, n = codegen.commands_to_events(cmds, OUT)
    assert n > 0 and len(ev) >= len(cmds)
    audio = opll.render(ev, n)
    assert float(abs(audio).max()) > 0.0, "le rendu est silencieux"
    print(f"  {len(cmds)} commandes -> {n} samples, crete {float(abs(audio).max()):.4f}")


# --- Fichier reel (saute s'il est absent) -----------------------------------

_REEL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "TODO_game-projects", "r-type_elements",
    "_audio", "rtype-YM2413.vgm")


def test_a_real_deflemask_export_converts_under_budget():
    if not os.path.exists(_REEL):
        print(f"  saute : {_REEL} absent")
        return
    v = vgm.parse(open(_REEL, "rb").read())
    infos = vgm.survey(v)
    assert infos, "aucune voie active dans un vrai fichier"
    voie = max(infos, key=lambda i: i.writes).channel
    cmds, _avis = vgm.to_commands(v, voie, 0, 100)  # 2 s
    st = codegen.stats(cmds)
    assert st["commands"] <= codegen.MAX_COMMANDS, st
    print(f"  rtype voie {voie} sur 100 ticks : {st['commands']} commandes, "
          f"{st['bytes']} octets")
