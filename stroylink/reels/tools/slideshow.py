#!/usr/bin/env python3
"""
slideshow.py - build a vertical Instagram Reel from still images + a voiceover.

Usage:
    python3 slideshow.py spec.json out.mp4 [--lang ru|kk] [--keep-temp]
                         [--workers N] [--no-overlay]

spec.json (paths are relative to the spec file):
{
  "images":   ["a.png", "b.png", ...],
  "audio":    "vo.mp3",                     # voiceover; video length = its length
  "segments": [
    {"image": 0, "start": 0.0, "end": 4.2,
     "motion": "zoom_in",                   # zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down | none
     "transition_in": "cut",                # cut | crossfade | wipe_left | wipe_up | flash
     "transition_duration": 0.5,            # optional, seconds (0.35-0.6 recommended)
     "zoom": 0.08,                          # optional, motion strength (default 0.08 = 8 %)
     "focus": [0.5, 0.5]},                  # optional, zoom centre (0..1, 0..1)
    ...
  ],
  "music": "bed.mp3",          # optional background music (looped, ducked under voice)
  "music_volume": 0.12,        # music level relative to the voice (0.12 = about -18 dB)
  "whoosh": true,              # soft whoosh on every non-cut transition (default true)
  "whoosh_db": -17,            # whoosh level relative to the voice, dB (default -17)
  "loudness": -14,             # final integrated loudness, LUFS (default -14)
  "plan": "plan.json",         # optional overlay.py plan (captions)
  "label": true,               # corner label "Визуализация (ИИ)" (or a custom string)
  "lang": "ru",                # label language for overlay.py (ru | kk)
  "end_card": {"text": "...", "subtext": "...", "seconds": 2.5}   # optional, overrides the plan
}

Timing model: segment boundaries are the moments the voice switches to the next
line. Segments are made contiguous (gaps are closed by extending the previous
segment), the first starts at 0 and the last is padded to the end of the audio.
A transition is centred on the boundary: it starts duration/2 before
`start` and ends duration/2 after it.

Motion is rendered with Pillow: every frame is a Lanczos resize of a
floating-point crop box from a 1.3x pre-scaled (Lanczos) cover image, so motion
is sub-pixel exact (no zoompan integer jitter). Frames are piped to ffmpeg.

Output: 1080x1920, 30 fps, H.264 High yuv420p (BT.709) + AAC 48 kHz,
+faststart, loudness-normalised (two-pass loudnorm). If a plan, label or end
card is given, overlay.py (same folder) burns them in as the last step.

Requires: ffmpeg + ffprobe in PATH, Python 3.8+, Pillow.
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("Pillow is not installed. Run:  pip install pillow")

W, H = 1080, 1920
FPS = 30
BASE_SCALE = 1.3            # images are pre-scaled to 1.3x the output (cover crop)
HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.join(HERE, "overlay.py")

MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "none")
TRANSITIONS = ("cut", "crossfade", "wipe_left", "wipe_up", "flash")
DEFAULT_TDUR = {"cut": 0.0, "crossfade": 0.5, "wipe_left": 0.6, "wipe_up": 0.55, "flash": 0.4}
DEFAULT_ZOOM = 0.08
WHOOSH_LEN = 0.75           # seconds
WHOOSH_PEAK = 0.42          # seconds from whoosh start to its loudest point


def die(msg):
    sys.exit("ERROR: " + msg)


def warn(msg):
    print("WARNING: " + msg, file=sys.stderr)


def need_tool(name):
    if not shutil.which(name):
        die("%s not found in PATH. Install ffmpeg (https://ffmpeg.org) and try again." % name)


def run(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die("%s failed:\n%s\n%s" % (what, " ".join(cmd), r.stderr.strip()[-3000:]))
    return r


def audio_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", path], capture_output=True, text=True)
    if r.returncode != 0:
        die("ffprobe cannot read %s:\n%s" % (path, r.stderr.strip()))
    info = json.loads(r.stdout)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        die("%s has no audio stream." % path)
    d = float(info["format"].get("duration") or 0)
    if d <= 0:
        die("Cannot determine duration of %s." % path)
    return d


def measure_loudness(path_or_args, extra_filter=""):
    """Return loudnorm's first-pass JSON (input_i, input_tp, ...)."""
    args = path_or_args if isinstance(path_or_args, list) else ["-i", path_or_args]
    af = (extra_filter + "," if extra_filter else "") + \
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"
    r = run(["ffmpeg", "-hide_banner", "-nostats"] + args + ["-af", af, "-f", "null", "-"],
            "loudness measurement")
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        die("Could not parse loudnorm output.")
    d = json.loads(m[-1])
    out = {}
    for k, v in d.items():
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


# ----------------------------------------------------------------------------
# Spec
# ----------------------------------------------------------------------------
def load_spec(path):
    try:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        die("Cannot read spec %s: %s" % (path, e))
    base = os.path.dirname(os.path.abspath(path))

    def resolve(p):
        if p is None:
            return None
        p = os.path.expanduser(str(p))
        return p if os.path.isabs(p) else os.path.join(base, p)

    images = [resolve(p) for p in spec.get("images", [])]
    if not images:
        die("spec: 'images' is empty.")
    for p in images:
        if not os.path.isfile(p):
            die("Image not found: %s" % p)
    audio = resolve(spec.get("audio"))
    if not audio or not os.path.isfile(audio):
        die("Audio (voiceover) not found: %s" % audio)
    music = resolve(spec.get("music"))
    if music and not os.path.isfile(music):
        die("Music not found: %s" % music)
    plan = resolve(spec.get("plan"))
    if plan and not os.path.isfile(plan):
        die("Overlay plan not found: %s" % plan)
    segs = spec.get("segments") or []
    if not segs:
        die("spec: 'segments' is empty.")
    return dict(images=images, audio=audio, music=music, plan=plan, segments=segs,
                music_volume=float(spec.get("music_volume", 0.12)),
                whoosh=bool(spec.get("whoosh", True)),
                whoosh_db=float(spec.get("whoosh_db", -17)),
                loudness=float(spec.get("loudness", -14)),
                label=spec.get("label", False), lang=spec.get("lang"),
                end_card=spec.get("end_card"))


def normalise_segments(raw, n_images, duration):
    segs = []
    for i, s in enumerate(raw, 1):
        where = "segment #%d" % i
        try:
            img = int(s["image"])
            start = float(s.get("start", 0))
            end = float(s.get("end", start))
        except (KeyError, TypeError, ValueError):
            die("%s: needs an integer 'image' and numeric 'start'/'end'." % where)
        if not 0 <= img < n_images:
            die("%s: image index %d out of range (0..%d)." % (where, img, n_images - 1))
        motion = str(s.get("motion", "zoom_in")).lower()
        if motion not in MOTIONS:
            die("%s: unknown motion %r. Use: %s" % (where, motion, ", ".join(MOTIONS)))
        tr = str(s.get("transition_in", "crossfade" if i > 1 else "cut")).lower()
        if tr not in TRANSITIONS:
            die("%s: unknown transition %r. Use: %s" % (where, tr, ", ".join(TRANSITIONS)))
        focus = s.get("focus", [0.5, 0.5])
        segs.append(dict(idx=i, image=img, start=start, end=end, motion=motion, tr=tr,
                         tdur=float(s.get("transition_duration", DEFAULT_TDUR[tr])),
                         zoom=float(s.get("zoom", DEFAULT_ZOOM)),
                         focus=(float(focus[0]), float(focus[1]))))
    segs.sort(key=lambda s: s["start"])
    # contiguous timeline
    if segs[0]["start"] > 0.01:
        warn("first segment starts at %.2fs - moved to 0." % segs[0]["start"])
    segs[0]["start"] = 0.0
    segs = [s for s in segs if s["start"] < duration - 0.05] or die("all segments start after the audio ends.")
    for a, b in zip(segs, segs[1:]):
        if abs(a["end"] - b["start"]) > 0.02:
            warn("segment #%d ends at %.2fs but #%d starts at %.2fs - boundary set to %.2fs."
                 % (a["idx"], a["end"], b["idx"], b["start"], b["start"]))
        a["end"] = b["start"]
    if abs(segs[-1]["end"] - duration) > 0.05:
        print("Last segment #%d end %.2fs -> %.2fs (audio length)." % (segs[-1]["idx"], segs[-1]["end"], duration))
    segs[-1]["end"] = duration
    for s in segs:
        if s["end"] - s["start"] < 0.3:
            die("segment #%d is shorter than 0.3s (%.2f..%.2f)." % (s["idx"], s["start"], s["end"]))
    # transitions: centred on the boundary, clamped to 40 % of the shorter neighbour
    segs[0]["tr"], segs[0]["tdur"] = "cut", 0.0
    for a, b in zip(segs, segs[1:]):
        if b["tr"] == "cut":
            b["tdur"] = 0.0
            continue
        lim = 0.4 * min(a["end"] - a["start"], b["end"] - b["start"])
        if b["tdur"] > lim:
            warn("segment #%d: transition %.2fs too long for its neighbours - %.2fs." % (b["idx"], b["tdur"], lim))
            b["tdur"] = lim
        b["tdur"] = max(b["tdur"], 2.0 / FPS)
    for k, s in enumerate(segs):
        nxt = segs[k + 1]["tdur"] if k + 1 < len(segs) else 0.0
        s["t0"] = max(0.0, s["start"] - s["tdur"] / 2)      # first visible moment
        s["t1"] = min(duration, s["end"] + nxt / 2)          # last visible moment
    return segs


# ----------------------------------------------------------------------------
# Camera (all in normalised base-image coordinates)
# ----------------------------------------------------------------------------
def ease(p):
    p = min(1.0, max(0.0, p))
    return 0.6 * p + 0.4 * (0.5 - 0.5 * math.cos(math.pi * p))


def smoothstep(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def clamp_cam(cam):
    """cam = (cx, cy, z); z >= 1 is magnification of the cover image."""
    cx, cy, z = cam
    z = max(1.0, z)
    hw, hh = 0.5 / z, 0.5 / z
    return (min(max(cx, hw), 1 - hw), min(max(cy, hh), 1 - hh), z)


def motion_endpoints(seg):
    a = seg["zoom"]
    fx, fy = seg["focus"]
    m = seg["motion"]
    if m == "zoom_in":
        return clamp_cam((fx, fy, 1.0)), clamp_cam((fx, fy, 1.0 + a))
    if m == "zoom_out":
        return clamp_cam((fx, fy, 1.0 + a)), clamp_cam((fx, fy, 1.0))
    if m == "none":
        return clamp_cam((fx, fy, 1.0)), clamp_cam((fx, fy, 1.0))
    z = 1.0 + max(a, 0.06) * 1.25          # pans need some margin to travel in
    lo, hi = 0.5 / z, 1 - 0.5 / z
    if m == "pan_left":     # camera moves left (image slides right)
        return (hi, fy, z), (lo, fy, z)
    if m == "pan_right":
        return (lo, fy, z), (hi, fy, z)
    if m == "pan_up":       # camera tilts up (image slides down)
        # vertical travel is long on a 9:16 frame - use about 70 % of it
        mid, span = 0.5, (hi - lo) * 0.7
        return (fx, mid + span / 2, z), (fx, mid - span / 2, z)
    # pan_down
    mid, span = 0.5, (hi - lo) * 0.7
    return (fx, mid - span / 2, z), (fx, mid + span / 2, z)


def lerp_cam(c0, c1, p):
    # zoom interpolated geometrically -> constant perceived zoom speed
    z = c0[2] * (c1[2] / c0[2]) ** p
    return (c0[0] + (c1[0] - c0[0]) * p, c0[1] + (c1[1] - c0[1]) * p, z)


def build_cameras(segs):
    """Attach a camera(t) function to every segment.

    A wipe is a before/after reveal: during it both images use the outgoing
    camera, so the two stages of a room line up exactly; the incoming segment
    then continues its own motion from that framing (no jump)."""
    for k, s in enumerate(segs):
        c0, c1 = motion_endpoints(s)
        s["c0"], s["c1"] = c0, c1
        s["hold_until"] = None
        if k > 0 and s["tr"] in ("wipe_left", "wipe_up"):
            prev = segs[k - 1]
            tw1 = s["start"] + s["tdur"] / 2
            s["hold_until"] = tw1
            s["c0"] = cam_at(prev, tw1)
    return segs


def cam_at(s, t):
    if s["hold_until"] is not None:
        if t <= s["hold_until"]:
            return None          # caller uses the previous segment's camera
        span = max(1e-6, s["t1"] - s["hold_until"])
        return lerp_cam(s["c0"], s["c1"], ease((t - s["hold_until"]) / span))
    span = max(1e-6, s["t1"] - s["t0"])
    return lerp_cam(s["c0"], s["c1"], ease((t - s["t0"]) / span))


# ----------------------------------------------------------------------------
# Frame rendering (runs in worker processes)
# ----------------------------------------------------------------------------
G = {}


def prepare_base(path):
    """Cover-crop to 9:16 and Lanczos-scale to 1.3x the output size."""
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    bw, bh = int(round(W * BASE_SCALE)), int(round(H * BASE_SCALE))
    sw, sh = im.size
    target = bw / bh
    if sw / sh > target:          # too wide: crop sides
        cw, ch = sh * target, sh
    else:
        cw, ch = sw, sw / target
    box = ((sw - cw) / 2, (sh - ch) / 2, (sw + cw) / 2, (sh + ch) / 2)
    if sw < W or sh < H:
        warn("%s is only %dx%d - it will be upscaled (may look soft)." % (os.path.basename(path), sw, sh))
    return im.resize((bw, bh), Image.LANCZOS, box=box)


def render_view(img_i, cam):
    base = G["bases"][img_i]
    bw, bh = base.size
    cx, cy, z = cam
    vw, vh = bw / z, bh / z
    x0, y0 = cx * bw - vw / 2, cy * bh - vh / 2
    return base.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + vw, y0 + vh))


def wipe_mask(kind, p):
    """L mask: 255 where the NEW image shows. Soft 10 px edge."""
    feather = 10
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    if kind == "wipe_left":     # divider travels right -> left, new image on its right
        x = (1 - p) * (W + 2 * feather) - feather
        d.rectangle((x, 0, W, H), fill=255)
    else:                       # wipe_up: divider travels bottom -> top, new image below
        y = (1 - p) * (H + 2 * feather) - feather
        d.rectangle((0, y, W, H), fill=255)
    return m.filter(ImageFilter.GaussianBlur(feather / 2)), (x if kind == "wipe_left" else y)


def draw_divider(img, kind, pos, alpha):
    """Thin white 'before/after' slider line with a soft shadow."""
    if alpha <= 0:
        return img
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if kind == "wipe_left":
        d.rectangle((pos - 7, 0, pos + 7, H), fill=(0, 0, 0, int(70 * alpha)))
        lay = lay.filter(ImageFilter.GaussianBlur(6))
        d = ImageDraw.Draw(lay)
        d.rectangle((pos - 3, 0, pos + 3, H), fill=(255, 255, 255, int(230 * alpha)))
    else:
        d.rectangle((0, pos - 7, W, pos + 7), fill=(0, 0, 0, int(70 * alpha)))
        lay = lay.filter(ImageFilter.GaussianBlur(6))
        d = ImageDraw.Draw(lay)
        d.rectangle((0, pos - 3, W, pos + 3), fill=(255, 255, 255, int(230 * alpha)))
    out = img.convert("RGBA")
    out.alpha_composite(lay)
    return out.convert("RGB")


def render_frame(k):
    t = k / FPS
    segs = G["segs"]
    # active segment = the one whose [start, end) contains t
    j = 0
    while j + 1 < len(segs) and t >= segs[j + 1]["start"]:
        j += 1
    cur = segs[j]
    # are we inside a transition? (incoming = cur, or the next one already started)
    inc = None
    if j + 1 < len(segs) and t >= segs[j + 1]["t0"]:
        oj, inc = j, segs[j + 1]
    elif j > 0 and t < cur["start"] + cur["tdur"] / 2:
        oj, inc = j - 1, cur
    if inc is None or inc["tr"] == "cut" or inc["tdur"] <= 0:
        cam = cam_at(cur, t)
        if cam is None:      # held after a wipe (rounding edge)
            cam = cam_at(segs[j - 1], t)
        return render_view(cur["image"], cam).tobytes()

    p = (t - inc["t0"]) / inc["tdur"]
    p = min(1.0, max(0.0, p))
    out_s = segs[oj]
    cam_out = cam_at(out_s, t) or cam_at(segs[oj - 1], t)
    a = render_view(out_s["image"], cam_out)
    kind = inc["tr"]
    if kind in ("wipe_left", "wipe_up"):
        b = render_view(inc["image"], cam_out)        # same framing -> aligned reveal
        pe = smoothstep(p)
        mask, pos = wipe_mask(kind, pe)
        img = Image.composite(b, a, mask)
        # divider fades in/out at the very ends
        alpha = min(1.0, pe / 0.12, (1 - pe) / 0.12)
        return draw_divider(img, kind, pos, alpha).tobytes()
    cam_in = cam_at(inc, t)
    b = render_view(inc["image"], cam_in)
    if kind == "crossfade":
        return Image.blend(a, b, smoothstep(p)).tobytes()
    # flash: old -> white -> new, white peak at the boundary
    white = G["white"]
    if p < 0.5:
        return Image.blend(a, white, 0.92 * smoothstep(p / 0.5)).tobytes()
    return Image.blend(b, white, 0.92 * (1 - smoothstep((p - 0.5) / 0.5))).tobytes()


def init_worker(images, segs):
    G["segs"] = segs
    G["bases"] = [prepare_base(p) for p in images]
    G["white"] = Image.new("RGB", (W, H), (255, 255, 255))


# ----------------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------------
def build_audio(sp, segs, duration, tmp):
    """Voice (+ whooshes) (+ ducked music) -> two-pass loudnorm -> 48 kHz WAV."""
    voice_l = measure_loudness(sp["audio"])
    vi = voice_l["input_i"]
    if not math.isfinite(vi) or vi < -70:
        warn("voiceover seems silent (%.1f LUFS)." % vi)
        vi = -23.0
    inputs = ["-i", sp["audio"]]
    chains = ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              "apad,atrim=0:%.4f[voice]" % duration]
    mix = ["[voice]"]
    n_in = 1

    tr_times = [s["start"] for s in segs[1:] if s["tr"] != "cut"]
    if sp["whoosh"] and tr_times:
        wpath = os.path.join(tmp, "whoosh.wav")
        fi = 0.30
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "anoisesrc=d=%.2f:c=pink:r=48000:a=0.6:s=7" % WHOOSH_LEN,
             "-af", "highpass=f=350,lowpass=f=3200,highpass=f=350,"
                    "afade=t=in:st=0:d=%.2f:curve=exp,"
                    "afade=t=out:st=%.2f:d=%.2f:curve=qsin,"
                    "aecho=0.6:0.5:35:0.25" % (WHOOSH_PEAK, WHOOSH_PEAK, WHOOSH_LEN - WHOOSH_PEAK - 0.02),
             "-ac", "2", wpath], "whoosh generation")
        wl = measure_loudness(wpath)
        gain_db = (vi + sp["whoosh_db"]) - wl["input_i"]
        inputs += ["-i", wpath]
        n = len(tr_times)
        chains.append("[%d:a]volume=%.2fdB,asplit=%d%s" % (
            n_in, gain_db, n, "".join("[w%d]" % i for i in range(n))))
        for i, t in enumerate(tr_times):
            st = t - WHOOSH_PEAK
            trim = ""
            if st < 0:
                trim, st = "atrim=start=%.3f,asetpts=PTS-STARTPTS," % (-st), 0
            chains.append("[w%d]%sadelay=%d:all=1[wd%d]" % (i, trim, int(round(st * 1000)), i))
            mix.append("[wd%d]" % i)
        n_in += 1

    if sp["music"]:
        ml = measure_loudness(sp["music"])
        mi = ml["input_i"] if math.isfinite(ml["input_i"]) and ml["input_i"] > -70 else -20.0
        vol = 20 * math.log10(max(sp["music_volume"], 1e-4))
        gain_db = (vi - mi) + vol
        inputs += ["-stream_loop", "-1", "-i", sp["music"]]
        fade_st = max(0.0, duration - 1.5)
        chains.append("[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      "atrim=0:%.4f,asetpts=PTS-STARTPTS,volume=%.2fdB,"
                      "afade=t=in:d=0.6,afade=t=out:st=%.3f:d=1.5[mus]" % (duration, gain_db, fade_st))
        # duck music under the voice
        chains[0] = chains[0].replace("[voice]", "[voice0]")
        chains.append("[voice0]asplit=2[voice][vside]")
        chains.append("[mus][vside]sidechaincompress=threshold=0.03:ratio=5:attack=40:"
                      "release=400:makeup=1[musd]")
        mix.append("[musd]")
        n_in += 1

    if len(mix) > 1:
        chains.append("%samix=inputs=%d:duration=first:normalize=0:dropout_transition=0[mix]"
                      % ("".join(mix), len(mix)))
        out_lbl = "[mix]"
    else:
        out_lbl = "[voice]"
    mixed = os.path.join(tmp, "mix.wav")
    script = os.path.join(tmp, "audio_filters.txt")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(chains))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs +
        ["-filter_complex_script", script, "-map", out_lbl, "-t", "%.4f" % duration,
         "-c:a", "pcm_f32le", "-ar", "48000", mixed], "audio mix")

    # two-pass loudnorm
    target = sp["loudness"]
    m = measure_loudness(mixed)
    ln = ("loudnorm=I=%.1f:TP=-1.5:LRA=20:measured_I=%.2f:measured_TP=%.2f:measured_LRA=%.2f:"
          "measured_thresh=%.2f:offset=%.2f:linear=true:print_format=summary"
          % (target, m["input_i"], m["input_tp"], m["input_lra"], m["input_thresh"],
             m["target_offset"]))
    final = os.path.join(tmp, "audio_final.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", mixed,
         "-af", ln + ",aresample=48000", "-t", "%.4f" % duration,
         "-c:a", "pcm_s16le", "-ar", "48000", final], "loudness normalisation")
    return final, vi


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Images + voiceover -> vertical Reel (1080x1920).")
    ap.add_argument("spec")
    ap.add_argument("output")
    ap.add_argument("--lang", choices=["ru", "kk"], help="label language (overrides spec 'lang')")
    ap.add_argument("--workers", type=int, default=0, help="render processes (default: CPU count)")
    ap.add_argument("--crf", type=int, default=18, help="x264 quality (default 18)")
    ap.add_argument("--no-overlay", action="store_true", help="skip captions/label/end card")
    ap.add_argument("--keep-temp", action="store_true")
    a = ap.parse_args()

    need_tool("ffmpeg")
    need_tool("ffprobe")
    sp = load_spec(a.spec)
    out = os.path.abspath(a.output)
    duration = audio_duration(sp["audio"])
    segs = normalise_segments(sp["segments"], len(sp["images"]), duration)
    build_cameras(segs)
    nframes = int(round(duration * FPS))
    print("Voiceover %.2fs -> %d frames, %d segments:" % (duration, nframes, len(segs)))
    for s in segs:
        print("  #%d  img %d  %6.2f-%6.2f  %-9s  in: %s%s" % (
            s["idx"], s["image"], s["start"], s["end"], s["motion"], s["tr"],
            "" if s["tr"] == "cut" else " (%.2fs)" % s["tdur"]))

    use_overlay = not a.no_overlay and bool(sp["plan"] or sp["label"] or sp["end_card"])
    if use_overlay and not os.path.isfile(OVERLAY):
        die("overlay.py not found next to slideshow.py (%s)." % OVERLAY)

    tmp = tempfile.mkdtemp(prefix="slideshow_")
    try:
        print("Audio: mixing + loudness normalisation ...")
        audio, vi = build_audio(sp, segs, duration, tmp)
        print("  voice was %.1f LUFS -> final target %.1f LUFS" % (vi, sp["loudness"]))

        stage = os.path.join(tmp, "slideshow.mkv") if use_overlay else out
        vcodec = ["-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1",
                  "-preset", "medium", "-crf", str(12 if use_overlay else a.crf),
                  "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60", "-bf", "2",
                  "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                  "-color_range", "tv"]
        if not use_overlay:
            vcodec += ["-maxrate", "12M", "-bufsize", "24M"]
        acodec = (["-c:a", "pcm_s16le"] if use_overlay else
                  ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
               "-framerate", str(FPS), "-i", "-", "-i", audio,
               "-map", "0:v", "-map", "1:a",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=lanczos,format=yuv420p"] + \
            vcodec + acodec + ["-t", "%.4f" % duration, "-movflags", "+faststart",
                               "-map_metadata", "-1", stage]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        workers = a.workers or max(1, (os.cpu_count() or 2))
        print("Video: rendering %d frames with %d worker(s) ..." % (nframes, workers))
        ctx = mp.get_context("spawn") if sys.platform == "win32" else mp.get_context()
        try:
            with ctx.Pool(workers, initializer=init_worker, initargs=(sp["images"], segs)) as pool:
                for k, buf in enumerate(pool.imap(render_frame, range(nframes), chunksize=4)):
                    proc.stdin.write(buf)
                    if k % (FPS * 5) == 0:
                        print("  %5.1fs / %.1fs" % (k / FPS, duration), flush=True)
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        if proc.wait() != 0:
            die("ffmpeg encoding failed (see above).")

        if use_overlay:
            plan = {"overlays": []}
            if sp["plan"]:
                with open(sp["plan"], encoding="utf-8") as fh:
                    raw = json.load(fh)
                plan = {"overlays": raw} if isinstance(raw, list) else raw
            if sp["end_card"]:
                plan["end_card"] = sp["end_card"]
            plan_path = os.path.join(tmp, "plan.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh, ensure_ascii=False)
            ocmd = [sys.executable, OVERLAY, stage, plan_path, out,
                    "--crf", str(a.crf)]
            lang = a.lang or sp["lang"]
            if lang:
                ocmd += ["--lang", lang]
            if isinstance(sp["label"], str) and sp["label"].strip():
                ocmd += ["--label-text", sp["label"]]
            elif sp["label"]:
                ocmd += ["--label"]
            print("Overlay: captions / label / end card via overlay.py ...")
            if subprocess.run(ocmd).returncode != 0:
                die("overlay.py failed (see above).")
        print("Done: %s" % out)
    finally:
        if a.keep_temp:
            print("Temp files kept in: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
