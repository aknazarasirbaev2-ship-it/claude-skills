#!/usr/bin/env python3
"""Cut a beat-synced vertical reel from video clips + a self-made royalty-free beat.

Usage: python3 clips.py spec.json out.mp4
spec = {
  "bpm": 128,
  "drop_beat": 13,                 # beat where the bass/clap "drop" starts (the reveal)
  "clips": [ {"file": "a.mp4", "start": 3.0, "beats": 3, "speed": 1.5, "flash_in": false}, ... ],
  "plan": "plan.json" (optional, captions via overlay.py),
  "end_card": {"text": "...", "seconds": 2.0} (optional)
}
Landscape clips are centre-cropped to 9:16. Every cut lands exactly on a beat.
"""
import json, os, subprocess, sys, tempfile, wave, math, random
import numpy as np

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    subprocess.run(cmd, check=True)


def probe(f):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", f]).decode().strip()
    w, h = map(int, out.split(",")[:2])
    return w, h


# ---------------- beat (synthesised, royalty-free) ----------------
def env(n, a, d):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / d)


def kick(n=int(0.45 * SR)):
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 7) * 1.0


def hat(n=int(0.06 * SR), open_=False):
    rng = np.random.default_rng(7)
    x = rng.standard_normal(n if not open_ else int(0.22 * SR))
    x = np.diff(np.concatenate([[0], x]))  # high-pass-ish
    t = np.arange(len(x)) / SR
    return x * np.exp(-t * (60 if not open_ else 14)) * 0.18


def clap(n=int(0.25 * SR)):
    rng = np.random.default_rng(3)
    x = rng.standard_normal(n)
    t = np.arange(n) / SR
    e = np.exp(-t * 22) + 0.6 * np.exp(-np.maximum(t - 0.012, 0) * 30) * (t > 0.012)
    return np.diff(np.concatenate([[0], x])) * e * 0.35


def bass(freq, n):
    t = np.arange(n) / SR
    f = freq * (1 + 0.6 * np.exp(-t * 30))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.tanh(2.2 * np.sin(ph)) * np.minimum(1, t / 0.005) * np.exp(-t * 1.6)
    return x * 0.55


def pad(freqs, n):
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.003 * t) for f in freqs)
    fade = np.minimum(1, t / 0.3) * np.minimum(1, (n / SR - t) / 0.3)
    return x / len(freqs) * fade * 0.07


def riser(n):
    rng = np.random.default_rng(11)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    x = np.diff(np.concatenate([[0], x]))
    return x * (t / t[-1]) ** 2 * 0.25


def add(buf, sig, at):
    i = int(at * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[: j - i]


def make_beat(total_beats, bpm, drop_beat, path):
    spb = 60.0 / bpm
    dur = math.ceil(total_beats) * spb + 0.6
    buf = np.zeros(int(dur * SR))
    # A minor-ish progression for the 808 (one chord per 4 beats)
    roots = [55.0, 43.65, 49.0, 41.2]  # A1, F1, G1, E1
    chords = [[220, 261.6, 329.6], [174.6, 220, 261.6], [196, 246.9, 293.7], [164.8, 207.7, 246.9]]
    for b in range(int(math.ceil(total_beats))):
        t = b * spb
        bar_pos = b % 4
        pre = b < drop_beat
        # hats on 8ths (16ths after the drop)
        for k in range(2 if pre else 4):
            add(buf, hat(), t + k * spb / (2 if pre else 4))
        if pre:
            if bar_pos in (0, 2):
                add(buf, kick() * 0.7, t)
        else:
            if bar_pos == 0 or (bar_pos == 2) or (bar_pos == 3 and b % 8 == 7):
                add(buf, kick(), t)
            if bar_pos in (1, 3):
                add(buf, clap(), t)
            if bar_pos == 0:
                r = roots[(b // 4) % 4]
                add(buf, bass(r, int(4 * spb * SR)), t)
                add(buf, pad(chords[(b // 4) % 4], int(4 * spb * SR)), t)
            if bar_pos == 2 and b % 8 == 6:
                add(buf, hat(open_=True), t + spb / 2)
    # riser into the drop + silence gap right before it (classic "drop")
    rs = max(0.0, (drop_beat - 4) * spb)
    add(buf, riser(int(4 * spb * SR)), rs)
    gap_a, gap_b = int((drop_beat * spb - spb / 2) * SR), int(drop_beat * spb * SR)
    buf[gap_a:gap_b] *= 0.15
    # tail fade
    fade = int(0.6 * SR)
    buf[-fade:] *= np.linspace(1, 0, fade)
    buf /= max(1e-9, np.max(np.abs(buf))) / 0.9
    stereo = np.stack([buf, buf], axis=1)
    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


# ---------------- video ----------------
def render_clip(c, dur, out, tmp):
    w, h = probe(c["file"])
    speed = float(c.get("speed", 1.0))
    src_len = dur * speed
    if w / h > 9 / 16:  # too wide: centre-crop width
        crop = f"crop=trunc(ih*9/16/2)*2:ih:(iw-trunc(ih*9/16/2)*2)*{c.get('x', 0.5)}:0"
    else:  # too tall: centre-crop height
        crop = "crop=iw:trunc(iw*16/9/2)*2:0:(ih-trunc(iw*16/9/2)*2)/2"
    vf = (f"{crop},scale=1080:1920:flags=lanczos,setpts=(PTS-STARTPTS)/{speed},fps=30,"
          f"eq=contrast={c.get('contrast', 1.05)}:saturation={c.get('saturation', 1.08)},format=yuv420p")
    if c.get("flash_in"):
        vf += ",fade=t=in:st=0:d=0.25:color=white"
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(c.get("start", 0)), "-t", f"{src_len:.3f}", "-i", c["file"],
         "-vf", vf, "-t", f"{dur:.4f}", "-an", "-c:v", "libx264", "-crf", "14", "-preset", "fast", out])


def main():
    spec_path, out = sys.argv[1], sys.argv[2]
    spec = json.load(open(spec_path))
    base = os.path.dirname(os.path.abspath(spec_path))
    bpm = spec.get("bpm", 128); spb = 60.0 / bpm
    tmp = tempfile.mkdtemp(prefix="clips_")
    parts = []
    total_beats = 0
    for i, c in enumerate(spec["clips"]):
        c = dict(c); c["file"] = os.path.join(base, c["file"])
        dur = c["beats"] * spb
        p = os.path.join(tmp, f"p{i:02d}.mp4")
        render_clip(c, dur, p, tmp)
        parts.append(p); total_beats += c["beats"]
        print(f"clip {i}: {os.path.basename(c['file'])} {dur:.2f}s")
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    video = os.path.join(tmp, "video.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video])
    beat = os.path.join(tmp, "beat.wav")
    make_beat(total_beats, bpm, spec.get("drop_beat", 8), beat)
    mixed = os.path.join(tmp, "mixed.mkv")
    vlen = total_beats * spb
    run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", beat, "-map", "0:v", "-map", "1:a",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-t", f"{vlen:.3f}", "-c:v", "copy", "-c:a", "pcm_s16le", mixed])
    if spec.get("plan") or spec.get("end_card"):
        cmd = [sys.executable, os.path.join(HERE, "overlay.py"), mixed,
               os.path.join(base, spec["plan"]) if spec.get("plan") else os.path.join(tmp, "empty.json"), out]
        if not spec.get("plan"):
            json.dump({"overlays": []}, open(os.path.join(tmp, "empty.json"), "w"))
        if spec.get("end_card"):
            cmd += ["--end-card", spec["end_card"]["text"], "--end-card-seconds", str(spec["end_card"].get("seconds", 2.0))]
        run(cmd)
    else:
        run(["ffmpeg", "-v", "error", "-y", "-i", mixed, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", out])
    print("Done:", out, f"({vlen:.2f}s, {total_beats} beats @ {bpm} bpm)")


if __name__ == "__main__":
    main()
