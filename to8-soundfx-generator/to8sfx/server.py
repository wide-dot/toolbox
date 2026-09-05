"""Interface web locale du generateur.

Serveur stdlib volontairement : l'outil ne doit rien demander d'autre que numpy
et ffmpeg. Un seul utilisateur, en local, donc un etat global suffit.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np

from . import analyze as an
from . import codegen, importer, instruments, melody, opll, parametric

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")

STATE: dict = {
    "audio": None,
    "analysis": None,
    "source_name": "",
    "preview_wav": None,
    "source_wav": None,
    "counter": 0,
}
LOCK = threading.Lock()


def _peaks(x: np.ndarray, columns: int = 1400) -> list[list[float]]:
    """Enveloppe min/max pour dessiner la forme d'onde et y poser les marqueurs."""
    n = len(x)
    if n == 0:
        return []
    cols = min(columns, n)
    edges = np.linspace(0, n, cols + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            b = a + 1
        seg = x[a:b]
        out.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
    return out


# --- Traitement -------------------------------------------------------------


def _build(params: dict) -> dict:
    mode = params.get("mode", "param")
    channel = int(params.get("channel", 4))
    name = params.get("name") or "NewSound"
    priority = int(params.get("priority", 1))
    warnings: list[str] = []
    ranking = None
    source_label = ""

    # audio aligne trame a trame avec `frames` : sert a l'appariement
    # d'instrument et a l'ajustement du patch custom.
    aligned_audio = None
    envelope = None  # RMS par trame : porte les attaques, donc les debuts de note
    rate = an.DEFAULT_RATE

    if mode == "wav":
        a0 = STATE["analysis"]
        if a0 is None:
            raise ValueError("aucun fichier audio charge")
        a, aligned_audio = an.slice_analysis(
            a0, STATE["audio"],
            params.get("start_ms"), params.get("end_ms"),
        )
        rate = a.rate
        warnings += list(a.warnings)
        frames = an.to_frames(
            a,
            instrument=int(params.get("instrument", 1)),
            smooth=int(params.get("smooth", 1)),
            pitch_shift_semitones=float(params.get("pitch_shift", 0.0)),
            gain_db=float(params.get("gain_db", 0.0)),
        )
        envelope = a.rms
        if params.get("trim", True):
            i0, i1 = an.trim_bounds(frames)
            hop = rate // an.FRAME_RATE
            frames = frames[i0:i1]
            envelope = envelope[i0:i1]
            aligned_audio = aligned_audio[i0 * hop : i1 * hop]
        sel = ""
        if params.get("start_ms") is not None or params.get("end_ms") is not None:
            sel = (f" [{float(params.get('start_ms') or 0)/1000:.2f}s"
                   f" - {float(params.get('end_ms') or a0.duration*1000)/1000:.2f}s]")
        source_label = STATE["source_name"] + sel
    else:
        sp = parametric.SweepParams(**{
            k: v for k, v in (params.get("sweep") or {}).items()
            if k in parametric.SweepParams.__dataclass_fields__
        })
        frames = parametric.sweep(sp)
        source_label = f"mode parametrique ({params.get('preset') or 'reglages manuels'})"

    if not frames:
        raise ValueError("aucune trame exploitable (le son est-il silencieux ?)")

    # --- mode melodique : caler sur des notes tenues ---
    notes = None
    tuning_used = 0.0
    melodic = bool(params.get("melodic"))
    if melodic:
        tc = params.get("melodic_tuning")
        tc = None if tc in (None, "", "auto") else float(tc)
        frames, note_list, tuning_used, tuning_conf = melody.quantize(
            frames,
            tuning_cents=tc,
            min_note_frames=int(params.get("melodic_min_frames", 3)),
            scale=params.get("melodic_scale") or "chromatique",
            root=int(params.get("melodic_root", 0)),
            retrigger=bool(params.get("melodic_retrigger", True)),
            envelope=envelope,
            onset_threshold_db=float(params.get("melodic_onset_db", 1.5)),
        )
        notes = [n.to_dict() for n in note_list]
        if not notes:
            warnings.append(
                "Mode melodique sans effet : aucune note stable detectee. Le son "
                "est probablement trop bruite ou trop court."
            )
        else:
            if tc is None and tuning_conf < 0.5:
                warnings.append(
                    f"Accordage peu fiable (confiance {tuning_conf:.2f}) : les notes "
                    "ne s'accordent pas sur un meme desaccord. Vibrato superieur au "
                    "demi-ton, ou source pile entre deux notes. Regler l'accordage a "
                    "la main plutot que de laisser l'automatique."
                )
            elif abs(tuning_used) > 8:
                warnings.append(
                    f"Source desaccordee de {tuning_used:+.0f} cents par rapport au la "
                    "440 ; le decalage a ete compense avant de caler les notes."
                )

    # --- instrument ---
    imode = params.get("instrument_mode", "fixed")
    if imode in ("auto", "interleave"):
        if mode != "wav":
            warnings.append(
                "Le choix automatique d'instrument a besoin d'un son source a "
                "imiter : sans fichier, l'instrument reste celui choisi a la main."
            )
        else:
            cost, cands = instruments.cost_matrix(aligned_audio, frames, rate, channel)
            ranking = instruments.rank_instruments(cost, cands)
            if imode == "auto":
                best = ranking[0]["instrument"]
                frames = [opll.Frame(f.voiced, f.fnum, f.block, f.volume, best, f.attack) for f in frames]
            else:
                per = instruments.interleave(
                    cost, cands, float(params.get("switch_penalty", 0.8))
                )
                frames = instruments.apply_instruments(frames, per)
                n_sw = sum(1 for i in range(1, len(per)) if per[i] != per[i - 1])
                warnings.append(
                    f"Entrelacement : {n_sw} bascule(s) d'instrument, soit "
                    f"{n_sw * 3} octets. A ecouter : le changement de patch sous "
                    "une enveloppe deja lancee peut aussi bien enrichir le timbre "
                    "que le salir."
                )

    # --- patch custom ---
    custom_patch = None
    if params.get("custom"):
        if mode == "wav" and aligned_audio is not None:
            custom_patch, _ = instruments.fit_custom_patch(
                aligned_audio, frames, rate, channel,
                seed_instrument=int(params.get("custom_seed", 1)),
                iterations=int(params.get("custom_iterations", 200)),
            )
        else:
            custom_patch = opll.rom_patch_dump(int(params.get("custom_seed", 1)))
        frames = [opll.Frame(f.voiced, f.fnum, f.block, f.volume, 0, f.attack) for f in frames]
        warnings.append(
            "Instrument custom ACTIF : la commande $FF ecrit les registres "
            "$00-$07, qui sont GLOBAUX a la puce. La musique de battlesquadron "
            "s'en sert (la voie 5 du theme in-game selectionne l'instrument 0) : "
            "son timbre sera casse pour le reste du niveau."
        )

    # --- commandes ---
    cmds, used, info = codegen.fit_to_budget(frames, custom_patch=custom_patch,
                                             quantize_pitch=not melodic)
    st = codegen.stats(cmds)
    if info["cents"] > 0 or info["vol_step"] > 1:
        detail = (f"hauteur quantifiee a {info['cents']:.0f} cents, "
                  if info["cents"] > 0 else "")
        warnings.append(
            f"Simplifie pour tenir dans les 255 commandes : {detail}"
            f"volume par pas de {info['vol_step']}."
        )
    if info["truncated"]:
        warnings.append(
            "Son TRONQUE : meme simplifie au maximum il depasse 255 commandes. "
            "Raccourcir la duree."
        )

    # --- rendu ---
    ev, nsamples = codegen.commands_to_events(cmds, channel)
    y = opll.render(ev, nsamples)

    with LOCK:
        STATE["counter"] += 1
        STATE["preview_wav"] = importer.wav_bytes(y)

    asm = codegen.to_asm(name, channel, cmds, priority=priority, source=source_label)

    return {
        "asm": asm,
        "stats": st,
        "info": info,
        "warnings": warnings,
        "ranking": ranking,
        "notes": notes,
        "melody": melody.describe([melody.Note(**{k: v for k, v in n.items()
                                                  if k in ("start", "end", "midi", "name", "freq")})
                                   for n in notes]) if notes else None,
        "tuning_cents": round(tuning_used, 1),
        "custom_patch": (" ".join(f"${b:02X}" for b in custom_patch) if custom_patch else None),
        "curves": {
            "freq": [round(opll.fnum_block_to_freq(f.fnum, f.block), 2) if f.voiced else 0
                     for f in used],
            "volume": [f.volume if f.voiced else None for f in used],
            "instrument": [f.instrument for f in used],
        },
        "preview": f"/api/preview.wav?t={STATE['counter']}",
        "const_line": f"soundFX.{name:22s} equ <id>",
        "call_line": f"        _soundFX.play soundFX.{name},{priority}",
    }


# --- HTTP -------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "to8sfx"

    def log_message(self, fmt, *args):  # silence
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if path == "/api/presets":
            return self._json({
                "presets": {k: v.to_dict() for k, v in parametric.PRESETS.items()},
                "instruments": opll.INSTRUMENTS,
                "scales": list(melody.SCALES),
                "notes": opll.NOTE_NAMES,
            })
        if path == "/api/preview.wav":
            data = STATE.get("preview_wav")
            if not data:
                return self._json({"error": "aucun preview"}, 404)
            return self._send(200, data, "audio/wav")
        if path == "/api/source.wav":
            data = STATE.get("source_wav")
            if not data:
                return self._json({"error": "aucune source"}, 404)
            return self._send(200, data, "audio/wav")
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        try:
            if path == "/api/upload":
                fname = self.headers.get("X-Filename", "source")
                suffix = os.path.splitext(fname)[1] or ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(body)
                    tmp = tf.name
                try:
                    x = an.load_audio(tmp)
                finally:
                    os.unlink(tmp)
                a = an.analyze(x)
                with LOCK:
                    STATE["audio"] = x
                    STATE["analysis"] = a
                    STATE["source_name"] = fname
                    STATE["source_wav"] = importer.wav_bytes(x, gain=1.0)
                return self._json({
                    "name": fname,
                    "duration": round(a.duration, 3),
                    "frames": a.n_frames,
                    "voiced_ratio": round(float(a.voiced.mean()), 3),
                    "warnings": a.warnings,
                    "f0": [round(v, 2) for v in a.f0.tolist()],
                    "rms": [round(float(v), 5) for v in a.rms.tolist()],
                    "peaks": _peaks(x),
                    "voiced": [bool(v) for v in a.voiced.tolist()],
                    "source": "/api/source.wav",
                })

            if path == "/api/generate":
                params = json.loads(body or b"{}")
                return self._json(_build(params))

        except Exception as exc:  # renvoyer l'erreur a l'ecran, pas dans un log
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)

        return self._json({"error": "not found"}, 404)


def serve(host: str = "127.0.0.1", port: int = 8731, open_browser: bool = True):
    opll.load_library()  # compile si besoin, avant d'annoncer que c'est pret
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"to8-soundfx-generator : {url}")
    print("Ctrl-C pour arreter.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\narret.")
