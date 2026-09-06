#!/usr/bin/env python3
"""Ligne de commande du generateur de bruitages soundFX (Thomson TO8).

    ./cli.py ui                                          interface web (l'atelier de creation)
    ./cli.py create --category explosion --seed 42 -o son.asm  tirer un bruitage au sort
    ./cli.py bank banque.json --out-dir build/                 generer la banque (2 fichiers .asm)
    ./cli.py wav laser.wav --name Laser                   depuis un fichier audio
    ./cli.py import <soundFX.asm> <label>                 relire un son existant
"""

from __future__ import annotations

import argparse
import os
import sys

from to8sfx import analyze as an
from to8sfx import codegen, importer, instruments, melody, opll


def _emit(args, frames, source_label, envelope=None):
    melodic = getattr(args, "melodic", False)
    if melodic:
        tc = getattr(args, "tuning_cents", None)
        frames, notes, tuning, conf = melody.quantize(
            frames,
            tuning_cents=tc,
            min_note_frames=args.min_note_frames,
            scale=args.scale,
            root=args.root,
            retrigger=not args.no_retrigger,
            envelope=envelope,
            onset_threshold_db=args.onset_db,
        )
        if notes:
            print(f"  melodie : {melody.describe(notes)}", file=sys.stderr)
            if tc is None:
                flag = "" if conf >= 0.5 else "  (PEU FIABLE, regler --tuning-cents)"
                print(f"  accordage {tuning:+.0f} cents, confiance {conf:.2f}{flag}",
                      file=sys.stderr)
        else:
            print("  mode melodique sans effet : aucune note stable detectee",
                  file=sys.stderr)

    custom_patch = None
    if getattr(args, "custom", False):
        custom_patch = opll.rom_patch_dump(args.custom_seed)
        frames = [opll.Frame(f.voiced, f.fnum, f.block, f.volume, 0, f.attack) for f in frames]
        print("ATTENTION : instrument custom actif, les registres $00-$07 sont "
              "globaux a la puce et la musique s'en sert.", file=sys.stderr)

    cmds, used, info = codegen.fit_to_budget(frames, custom_patch=custom_patch,
                                             quantize_pitch=not melodic)
    st = codegen.stats(cmds)
    asm = codegen.to_asm(args.name, args.channel, cmds, priority=args.priority,
                         source=source_label)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(asm)
        print(f"ecrit : {args.out}")
    else:
        print(asm)

    print(f"  {st['commands']} commandes / 255, {st['bytes']} octets, "
          f"{st['seconds']:.2f} s, voie {args.channel}", file=sys.stderr)
    if info["cents"] or info["vol_step"] > 1:
        print(f"  simplifie : hauteur {info['cents']:.0f} cents, volume par "
              f"{info['vol_step']}", file=sys.stderr)
    if info["truncated"]:
        print("  TRONQUE : depasse 255 commandes meme simplifie au maximum",
              file=sys.stderr)

    if args.wav:
        ev, n = codegen.commands_to_events(cmds, args.channel)
        importer.write_wav(args.wav, opll.render(ev, n))
        print(f"preview : {args.wav}", file=sys.stderr)


def cmd_create(args):
    from to8sfx import design as dz
    from to8sfx import rhythm
    # Quatrieme frontiere qui produit de l'assembleur : elle n'emprunte ni le
    # serveur ni la banque, donc elle porte le garde elle-meme.
    rhythm.check_any_channel(args.channel)
    p = dz.randomize(args.category, args.seed)
    frames, noise = dz.render(p)
    cmds, _used, info = codegen.fit_to_budget(
        frames, noise=noise, channel=args.channel,
        noise_pitch=p.noise_pitch, noise_vol=p.noise_vol)
    st = codegen.stats(cmds)
    asm = codegen.to_asm(args.name, args.channel, cmds, priority=args.priority,
                         source=f"{args.category}, graine {args.seed}")
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(asm)
        print(f"ecrit : {args.out}")
    else:
        print(asm)
    print(f"  {st['commands']} commandes / 255, {st['bytes']} octets, "
          f"{st['seconds']:.2f} s, voie {args.channel}", file=sys.stderr)
    if info["truncated"]:
        print("  TRONQUE : raccourcir la chute", file=sys.stderr)
    if args.wav:
        ev, n = codegen.commands_to_events(cmds, args.channel)
        importer.write_wav(args.wav, opll.render(ev, n))
        print(f"preview : {args.wav}", file=sys.stderr)


def cmd_bank(args):
    from to8sfx import bank as bk
    b = bk.Bank.from_json(open(args.source).read())
    out = b.build()
    os.makedirs(args.out_dir, exist_ok=True)
    for fname, key in (("soundFX.asm", "asm"), ("soundFX.const.asm", "const")):
        path = os.path.join(args.out_dir, fname)
        with open(path, "w") as fh:
            fh.write(out[key])
        print(f"ecrit : {path}")
    print(f"  {len(out['per_sound'])} son(s), {out['bytes']} octets")
    for w in out["warnings"]:
        print(f"  ! {w}", file=sys.stderr)


def cmd_wav(args):
    x = an.load_audio(args.input)
    a = an.analyze(x)
    a, x = an.slice_analysis(a, x, args.start_ms, args.end_ms)
    if args.start_ms is not None or args.end_ms is not None:
        print(f"  selection : {a.duration:.2f} s ({a.n_frames} trames)", file=sys.stderr)
    for w in a.warnings:
        print(f"  ! {w}", file=sys.stderr)
    frames = an.to_frames(a, instrument=args.instrument, smooth=args.smooth,
                          pitch_shift_semitones=args.pitch_shift, gain_db=args.gain_db)
    i0, i1 = an.trim_bounds(frames)
    hop = a.rate // an.FRAME_RATE
    frames, x = frames[i0:i1], x[i0 * hop : i1 * hop]
    envelope = a.rms[i0:i1]
    if not frames:
        sys.exit("aucune trame exploitable (son silencieux ?)")

    if args.auto_instrument or args.interleave:
        cost, cands = instruments.cost_matrix(x, frames, a.rate, args.channel)
        rank = instruments.rank_instruments(cost, cands)
        print("  instruments les plus proches : " + ", ".join(
            f"{r['instrument']} {r['name']} ({r['relative']:.2f})" for r in rank[:4]),
            file=sys.stderr)
        if args.interleave:
            per = instruments.interleave(cost, cands, args.switch_penalty)
            frames = instruments.apply_instruments(frames, per)
            n_sw = sum(1 for i in range(1, len(per)) if per[i] != per[i - 1])
            print(f"  entrelacement : {n_sw} bascule(s) = {n_sw*3} octets", file=sys.stderr)
        else:
            best = rank[0]["instrument"]
            frames = [opll.Frame(f.voiced, f.fnum, f.block, f.volume, best, f.attack) for f in frames]
    _emit(args, frames, args.input, envelope)


def cmd_import(args):
    text = open(args.source).read()
    channel, cmds = importer.parse_asm_sound(text, args.label)
    st = codegen.stats(cmds)
    print(f"{args.label} : voie {channel}, {st['commands']} commandes, "
          f"{st['bytes']} octets, {st['seconds']:.2f} s")
    if args.wav:
        ev, n = codegen.commands_to_events(cmds, channel)
        importer.write_wav(args.wav, opll.render(ev, n))
        print(f"rendu : {args.wav}")


def cmd_ui(args):
    from to8sfx.server import serve
    serve(port=args.port, open_browser=not args.no_browser)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--name", default="NewSound", help="nom du son (label assembleur)")
        p.add_argument("--channel", type=int, default=4,
                       help="voie YM2413 (4 = la seule libre en jeu sur battlesquadron)")
        p.add_argument("--priority", type=int, default=1)
        p.add_argument("-o", "--out", help="fichier .asm de sortie (defaut : stdout)")
        p.add_argument("--wav", help="ecrire aussi un preview .wav du rendu")
        p.add_argument("--custom", action="store_true",
                       help="utiliser l'instrument custom ($FF) - casse le timbre de la musique")
        p.add_argument("--custom-seed", type=int, default=1, dest="custom_seed")
        p.add_argument("--melodic", action="store_true",
                       help="caler la hauteur sur des notes tenues (jingles, bonus)")
        p.add_argument("--min-note-frames", type=int, default=3, dest="min_note_frames",
                       help="duree minimale d'une note, en trames de 20 ms")
        p.add_argument("--no-retrigger", action="store_true", dest="no_retrigger",
                       help="enchainer les notes en legato au lieu de les reattaquer")
        p.add_argument("--tuning-cents", type=float, default=None, dest="tuning_cents",
                       help="accordage force en cents (defaut : mesure sur la source)")
        p.add_argument("--onset-db", type=float, default=1.5, dest="onset_db",
                       help="sensibilite aux attaques, en dB (0 = ne pas separer "
                            "les notes de meme hauteur)")
        p.add_argument("--scale", default="chromatique", choices=list(melody.SCALES))
        p.add_argument("--root", type=int, default=0,
                       help="tonique de la gamme, 0 = C .. 11 = B")

    p = sub.add_parser("create", help="tirer un bruitage au sort")
    common(p)
    p.add_argument("--category", default="tir")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("bank", help="generer les deux .asm depuis une banque JSON")
    p.add_argument("source", help="fichier JSON de la banque")
    p.add_argument("--out-dir", default=".", dest="out_dir")
    p.set_defaults(func=cmd_bank)

    p = sub.add_parser("wav", help="depuis un fichier audio")
    common(p)
    p.add_argument("input")
    p.add_argument("--instrument", type=int, default=15)
    p.add_argument("--start-ms", type=float, default=None, dest="start_ms",
                   help="debut de la selection dans le fichier source (ms)")
    p.add_argument("--end-ms", type=float, default=None, dest="end_ms",
                   help="fin de la selection (ms)")
    p.add_argument("--smooth", type=int, default=1,
                   help="filtre median sur la hauteur, en trames (1 = aucun)")
    p.add_argument("--pitch-shift", type=float, default=0.0, dest="pitch_shift")
    p.add_argument("--gain-db", type=float, default=0.0, dest="gain_db")
    p.add_argument("--auto-instrument", action="store_true", dest="auto_instrument")
    p.add_argument("--interleave", action="store_true")
    p.add_argument("--switch-penalty", type=float, default=0.8, dest="switch_penalty")
    p.set_defaults(func=cmd_wav)

    p = sub.add_parser("import", help="relire un bloc soundFX existant")
    p.add_argument("source")
    p.add_argument("label", help="ex: soundFX.ExplosionSound.data")
    p.add_argument("--wav")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("ui", help="interface web locale")
    p.add_argument("--port", type=int, default=8731)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_ui)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
