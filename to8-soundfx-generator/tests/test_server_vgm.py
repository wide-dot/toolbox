"""Les endpoints de l'onglet VGM, appeles en direct (sans reseau).

Meme parti que test_server_design : la logique vit dans les fonctions de
traitement, on les appelle telles quelles.

Ces tests gardent aussi la contrainte posee au depart : l'onglet VGM ne doit
rien casser des deux autres. Le dernier test le verifie explicitement, parce que
l'etat du serveur est global et qu'un import VGM pourrait tres bien pietiner
l'analyse audio en place.
"""

from to8sfx import codegen, design, server, vgm

from tests.test_vgm import END, note_on, vgm_bytes, w, wait50

OUT = 4


def _upload(body: bytes = None, name: str = "test.vgm") -> dict:
    if body is None:
        body = note_on(ch=1, inst=5) + wait50(20) + w(0x11, 0x66) + wait50(20) + END
    return server._vgm_upload(vgm_bytes(body), name)


def test_upload_returns_the_channel_inventory():
    out = _upload()
    for key in ("name", "n_ticks", "seconds", "clock", "channels", "warnings"):
        assert key in out, f"cle absente de la reponse : {key}"
    assert out["name"] == "test.vgm"
    assert out["n_ticks"] == 40, out["n_ticks"]
    voies = {c["channel"] for c in out["channels"]}
    assert voies == {1}, voies
    assert out["channels"][0]["instrument_names"] == ["Clarinet"], out["channels"][0]
    print(f"  {out['n_ticks']} ticks, voies actives {sorted(voies)}, "
          f"{out['channels'][0]['instrument_names']}")


def test_upload_refuses_a_vgm_without_ym2413():
    try:
        server._vgm_upload(vgm_bytes(wait50(1) + END, ym2413=0, sn76489=3579545),
                           "psg.vgm")
    except ValueError as e:
        assert "SN76489" in str(e), e
        print("  export SN76489 refuse en nommant la puce")
        return
    raise AssertionError("un VGM sans YM2413 a ete accepte")


def test_render_returns_everything_the_ui_needs():
    _upload()
    out = server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                              "out_channel": OUT, "name": "Laser"})
    for key in ("asm", "stats", "preview", "trace", "warnings"):
        assert key in out, f"cle absente de la reponse : {key}"
    assert "soundFX.Laser.data" in out["asm"], out["asm"][:200]
    assert out["stats"]["commands"] > 0
    assert len(out["trace"]) == 40, len(out["trace"])
    assert out["preview"].startswith("/api/preview.wav")
    print(f"  {out['stats']['commands']} commandes, {out['stats']['bytes']} octets, "
          f"{out['stats']['seconds']:.2f} s")


def test_render_honours_the_selection_window():
    """Le budget affiche doit etre celui de la fenetre, sinon le compteur ment
    et on livre un bloc tronque sans le savoir."""
    _upload()
    court = server._vgm_render({"src_channel": 1, "start_frame": 0,
                               "end_frame": 10, "out_channel": OUT, "name": "A"})
    long = server._vgm_render({"src_channel": 1, "start_frame": 0,
                              "end_frame": 40, "out_channel": OUT, "name": "A"})
    assert court["stats"]["seconds"] < long["stats"]["seconds"], \
        (court["stats"], long["stats"])
    assert len(court["trace"]) == 10, len(court["trace"])
    print(f"  fenetre 0-10 : {court['stats']['seconds']:.2f} s ; "
          f"0-40 : {long['stats']['seconds']:.2f} s")


def test_render_writes_the_output_channel_in_the_header():
    """La voie de sortie part dans le deuxieme octet de l'en-tete du bloc : une
    erreur ici joue le bruitage sur la mauvaise voie de la puce."""
    _upload()
    out = server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                              "out_channel": 2, "name": "Laser"})
    assert "voie YM2413 2" in out["asm"], out["asm"][:400]
    print("  voie de sortie 2 portee dans l'en-tete")


def test_render_rejects_an_impossible_output_channel():
    _upload()
    try:
        server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                            "out_channel": 12, "name": "Laser"})
    except ValueError as e:
        print(f"  voie de sortie 12 refusee : {e}")
        return
    raise AssertionError("une voie de sortie inexistante a ete acceptee")


def test_render_without_an_upload_says_so():
    server.STATE["vgm"] = None
    try:
        server._vgm_render({"src_channel": 0, "start_frame": 0, "end_frame": 10,
                            "out_channel": OUT, "name": "X"})
    except ValueError as e:
        assert "vgm" in str(e).lower(), e
        print(f"  rendu sans fichier refuse : {e}")
        return
    raise AssertionError("un rendu sans fichier charge a ete accepte")


def test_render_reports_a_window_over_budget():
    """Un VGM dense doit dire qu'il deborde, pas livrer un bloc que le driver
    lira de travers."""
    body = note_on(ch=1)
    for i in range(300):  # une hauteur differente par tick : rien a dedupliquer
        body += wait50(1) + w(0x11, i & 0xFF)
    _upload(body + END)
    out = server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 301,
                              "out_channel": OUT, "name": "Dense"})
    joined = " ".join(out["warnings"]).lower()
    assert "255" in joined, out["warnings"]
    assert out["stats"]["over_budget"], out["stats"]
    print(f"  {out['stats']['commands']} commandes : debordement signale")


def test_the_generated_block_is_replayable_by_the_listen_endpoint():
    """L'onglet sort un bloc a copier : il doit se relire par le chemin deja
    offert a l'utilisateur pour verifier ce qu'il a collé dans le jeu."""
    _upload()
    out = server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                              "out_channel": OUT, "name": "Laser"})
    relu = server._listen({"asm": out["asm"]})
    assert relu["channel"] == OUT, relu["channel"]
    assert relu["stats"]["commands"] == out["stats"]["commands"], \
        (relu["stats"], out["stats"])
    print(f"  bloc relu par /api/listen : {relu['stats']['commands']} commandes")


# --- Non-regression des deux autres onglets ---------------------------------


def test_a_vgm_import_leaves_the_audio_analysis_alone():
    """L'etat du serveur est global. Si l'import VGM ecrasait STATE['audio'] ou
    STATE['analysis'], l'onglet Fichier audio perdrait son fichier sans rien
    dire — exactement la regression que l'auteur a demande d'eviter."""
    server.STATE["audio"] = "sentinelle-audio"
    server.STATE["analysis"] = "sentinelle-analyse"
    server.STATE["source_name"] = "sentinelle-nom"
    _upload()
    server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                        "out_channel": OUT, "name": "Laser"})
    assert server.STATE["audio"] == "sentinelle-audio", server.STATE["audio"]
    assert server.STATE["analysis"] == "sentinelle-analyse"
    assert server.STATE["source_name"] == "sentinelle-nom"
    server.STATE["audio"] = server.STATE["analysis"] = None
    server.STATE["source_name"] = ""
    print("  l'analyse audio survit a un import VGM")


def test_a_vgm_import_leaves_the_bank_alone():
    """La banque n'accueille pas les sons VGM (decision de conception) : elle ne
    doit pas non plus etre abimee par leur passage."""
    avant = server._bank_add({"name": "Temoin", "category": "tir",
                              "params": design.randomize("tir", seed=3).to_dict(),
                              "channel": 4, "priority": 1})
    n = len(avant["sounds"])
    _upload()
    server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                        "out_channel": OUT, "name": "Laser"})
    apres = server._bank_view()
    assert len(apres["sounds"]) == n, (n, len(apres["sounds"]))
    assert apres["sounds"][-1]["name"] == "Temoin"
    server._bank_remove({"index": n - 1})
    print(f"  banque intacte : {len(apres['sounds'])} son(s), le temoin en place")


def test_the_create_tab_still_renders_after_a_vgm_import():
    _upload()
    server._vgm_render({"src_channel": 1, "start_frame": 0, "end_frame": 40,
                        "out_channel": OUT, "name": "Laser"})
    p = design.randomize("tir", seed=11)
    out = server._render_design({"params": p.to_dict(), "channel": 4,
                                 "name": "Laser2", "priority": 1})
    assert out["stats"]["commands"] > 0
    assert "soundFX.Laser2.data" in out["asm"]
    print(f"  onglet Creer toujours fonctionnel : {out['stats']['commands']} commandes")


# --- Trace complete d'une voie ----------------------------------------------
#
# Ecart assume par rapport a la spec, qui ne prevoyait que deux points d'entree.
# L'interface doit dessiner TOUTE la voie pour qu'on puisse y decouper une
# fenetre ; la faire renvoyer par /api/vgm/render reexpedierait le fichier
# entier a chaque mouvement de souris, et la faire renvoyer par /api/vgm/upload
# obligerait a envoyer les neuf voies alors qu'une seule est regardee.


def test_trace_covers_the_whole_channel():
    _upload()
    out = server._vgm_trace({"src_channel": 1})
    assert len(out["trace"]) == 40, len(out["trace"])
    assert out["trace"][0]["on"], out["trace"][0]
    assert out["trace"][0]["hz"] > 0
    print(f"  trace complete : {len(out['trace'])} ticks")


def test_trace_without_an_upload_says_so():
    server.STATE["vgm"] = None
    try:
        server._vgm_trace({"src_channel": 0})
    except ValueError as e:
        assert "vgm" in str(e).lower(), e
        print(f"  trace sans fichier refusee : {e}")
        return
    raise AssertionError("une trace sans fichier charge a ete acceptee")
