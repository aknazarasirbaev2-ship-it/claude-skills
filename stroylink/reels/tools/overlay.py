#!/usr/bin/env python3
"""
overlay.py - burn captions, a corner label and an end card into a vertical Reel.

Usage:
    python3 overlay.py in.mp4 plan.json out.mp4 [--lang ru|kk] [--label]
                       [--label-text TEXT] [--end-card TEXT]
                       [--end-card-seconds N] [--keep-temp] [--dry-run]

How it works: every caption is rendered to a small transparent PNG with Pillow
(big bold caps, white text, black outline, soft dark box + shadow). ffmpeg then
overlays each PNG with an alpha fade in/out. No drawtext / libass, so Cyrillic
and Kazakh letters never depend on system fonts or ffmpeg build options.

Output: 1080x1920, H.264 High + AAC, yuv420p, 30 fps, +faststart.
Duration of the output equals the duration of the input.

Requires: ffmpeg + ffprobe in PATH, Python 3.8+, Pillow.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    sys.exit("Pillow is not installed. Run:  pip install pillow")

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
W, H = 1080, 1920
FPS = 30
SAFE_TOP = 220          # Instagram UI covers the top ~220 px
SAFE_BOTTOM = 420       # ...and the bottom ~420 px (caption, buttons)
SIDE_MARGIN = 70        # left/right margin for the text box (incl. shadow)
FADE = 0.25             # default caption fade, seconds
HERE = os.path.dirname(os.path.abspath(__file__))

FONT_CANDIDATES = [
    os.path.join(HERE, "fonts", "Inter-ExtraBold.otf"),
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

LABELS = {"ru": "Визуализация (ИИ)", "kk": "Визуализация (AI)"}

# Style presets. box = RGBA of the soft box (None = no box, outline only).
STYLES = {
    # default caption: white text, dark soft box
    "step":   dict(size=96,  color=(255, 255, 255), box=(0, 0, 0, 165),
                   stroke=6, max_lines=3, pad=(44, 28), radius=34),
    # opening hook: bigger, same look
    "hook":   dict(size=122, color=(255, 255, 255), box=(0, 0, 0, 175),
                   stroke=7, max_lines=4, pad=(52, 36), radius=40),
    # yellow highlight box, dark text (good for "ГОТОВО")
    "accent": dict(size=112, color=(20, 20, 20), box=(255, 205, 0, 245),
                   stroke=0, max_lines=3, pad=(52, 32), radius=40),
    # no box, just thick outline + shadow
    "plain":  dict(size=100, color=(255, 255, 255), box=None,
                   stroke=9, max_lines=3, pad=(20, 16), radius=0),
}
DEFAULT_STYLE = "step"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def die(msg):
    sys.exit("ERROR: " + msg)


def warn(msg):
    print("WARNING: " + msg, file=sys.stderr)


def find_font(user_font=None):
    cands = ([user_font] if user_font else []) + FONT_CANDIDATES
    for p in cands:
        if p and os.path.isfile(p):
            return p
    die("No bold font with Cyrillic found. Pass one with --font /path/to/font.ttf "
        "(e.g. DejaVuSans-Bold.ttf).")


def need_tool(name):
    if not shutil.which(name):
        die("%s not found in PATH. Install ffmpeg (https://ffmpeg.org) and try again." % name)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True)
    if out.returncode != 0:
        die("ffprobe cannot read %s:\n%s" % (path, out.stderr.strip()))
    info = json.loads(out.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not v:
        die("%s has no video stream." % path)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"].get("duration") or v.get("duration") or 0)
    if dur <= 0:
        die("Cannot determine duration of %s." % path)
    return dict(w=int(v["width"]), h=int(v["height"]), duration=dur, audio=has_audio)


class Fonts:
    def __init__(self, path):
        self.path = path
        self._cache = {}
        self._notdef = None

    def get(self, size):
        size = int(size)
        if size not in self._cache:
            self._cache[size] = ImageFont.truetype(self.path, size)
        return self._cache[size]

    def missing_glyphs(self, text):
        """Characters the font draws as the 'missing glyph' box."""
        f = self.get(60)

        def shape(ch):
            im = Image.new("L", (90, 90), 0)
            ImageDraw.Draw(im).text((10, 10), ch, font=f, fill=255)
            return im.tobytes()

        if self._notdef is None:
            self._notdef = shape("\uFFFF")
        return sorted(ch for ch in set(text)
                      if not ch.isspace() and shape(ch) == self._notdef)


def _greedy(words, f, max_w, stroke):
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if f.getlength(trial) + 2 * stroke <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap_fit(text, fonts, size, max_w, stroke, max_lines):
    """Word wrap; shrink the font until it fits max_w and max_lines, then
    balance the lines (no lonely word on the last line)."""
    words = text.split()
    min_size = 44
    while True:
        f = fonts.get(size)
        ok = all(f.getlength(w) + 2 * stroke <= max_w for w in words)
        if ok:
            lines = _greedy(words, f, max_w, stroke)
            if len(lines) <= max_lines:
                # narrow the width as far as possible without adding a line
                lo, hi = int(max(f.getlength(w) for w in words)) + 2 * stroke, int(max_w)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if len(_greedy(words, f, mid, stroke)) <= len(lines):
                        hi = mid
                    else:
                        lo = mid + 1
                return size, _greedy(words, f, hi, stroke)
        if size <= min_size:
            if ok:
                return size, lines
            die("Word too long to fit the screen even at %dpx: %r" % (min_size, text))
        size -= 4


def render_caption(text, fonts, style, size_override=None, color_override=None,
                   max_w=None):
    """Return an RGBA PIL image (tight, with room for the shadow)."""
    st = dict(style)
    if size_override:
        st["size"] = int(size_override)
    if color_override:
        st["color"] = tuple(color_override)
    shadow_pad = 46
    padx, pady = st["pad"]
    max_w = max_w or (W - 2 * SIDE_MARGIN)
    inner_w = max_w - 2 * padx
    size, lines = wrap_fit(text, fonts, st["size"], inner_w, st["stroke"], st["max_lines"])
    f = fonts.get(size)
    sw = st["stroke"] if st["stroke"] else 0
    # (stroke scales a little if the font was shrunk)
    sw = max(0, round(sw * size / st["size"])) if sw else 0

    asc = -f.getbbox("Н", anchor="ls")[1]   # cap height above baseline
    desc = int(size * 0.20)        # room for tails of Щ Қ Ң Ү
    pitch = int(size * 1.16)
    text_w = max(int(f.getlength(l)) for l in lines)
    block_h = asc + (len(lines) - 1) * pitch + desc
    box_w = text_w + 2 * padx + 2 * sw
    box_h = block_h + 2 * pady + 2 * sw
    cw, ch = box_w + 2 * shadow_pad, box_h + 2 * shadow_pad
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    bx0, by0 = shadow_pad, shadow_pad
    bx1, by1 = bx0 + box_w, by0 + box_h
    if st["box"]:
        # soft drop shadow
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((bx0, by0 + 10, bx1, by1 + 10),
                                             st["radius"], fill=(0, 0, 0, 120))
        sh = sh.filter(ImageFilter.GaussianBlur(14))
        img = Image.alpha_composite(img, sh)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((bx0, by0, bx1, by1), st["radius"], fill=st["box"])
    else:
        # no box: soft glow behind the letters for readability
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        dsh = ImageDraw.Draw(sh)
        y = by0 + pady + sw + asc
        for ln in lines:
            x = bx0 + (box_w - f.getlength(ln)) / 2
            dsh.text((x, y + 6), ln, font=f, fill=(0, 0, 0, 200), anchor="ls",
                     stroke_width=sw + 4, stroke_fill=(0, 0, 0, 200))
            y += pitch
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        img = Image.alpha_composite(img, sh)

    d = ImageDraw.Draw(img)
    y = by0 + pady + sw + asc
    for ln in lines:
        x = bx0 + (box_w - f.getlength(ln)) / 2
        d.text((x, y), ln, font=f, fill=st["color"] + (255,), anchor="ls",
               stroke_width=sw, stroke_fill=(0, 0, 0, 235) if sw else None)
        y += pitch
    return img, (bx0, by0, bx1, by1)


def place_y(position, inner_h, shadow_pad):
    """Top y of the PNG so that the *box* sits in the safe zone."""
    top, bottom = SAFE_TOP, H - SAFE_BOTTOM
    if position == "top":
        box_top = top + 110   # leaves room for the corner label
    elif position == "bottom":
        box_top = bottom - inner_h - 30
    else:  # center = middle of the safe zone
        box_top = (top + bottom) // 2 - inner_h // 2
    box_top = max(top, min(box_top, bottom - inner_h))
    return box_top - shadow_pad


def render_label(text, fonts):
    size = 34
    f = fonts.get(size)
    padx, pady = 22, 14
    tw = int(f.getlength(text))
    bw, bh = tw + 2 * padx, int(size * 0.74) + int(size * 0.25) + 2 * pady
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), 18, fill=(0, 0, 0, 140))
    asc = -f.getbbox("Н", anchor="ls")[1]
    d.text((padx, pady + asc), text, font=f, fill=(255, 255, 255, 235), anchor="ls")
    return img


def render_end_card(text, subtext, fonts):
    """Full-frame PNG: dim layer + CTA block in the safe zone."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 150))
    cta, (bx0, by0, bx1, by1) = render_caption(text, fonts, STYLES["accent"],
                                               size_override=104)
    sub_img = None
    gap = 36
    if subtext:
        sub_img, _ = render_caption(subtext, fonts, STYLES["plain"], size_override=64)
    ch = cta.height + (gap + sub_img.height if sub_img else 0)
    y0 = (SAFE_TOP + (H - SAFE_BOTTOM)) // 2 - ch // 2
    img.alpha_composite(cta, ((W - cta.width) // 2, y0))
    if sub_img:
        img.alpha_composite(sub_img, ((W - sub_img.width) // 2, y0 + cta.height + gap))
    return img


# ----------------------------------------------------------------------------
# Plan loading / validation
# ----------------------------------------------------------------------------
def load_plan(path, duration):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        die("Cannot read plan %s: %s" % (path, e))
    if isinstance(raw, list):
        items, end_card, label = raw, None, None
    elif isinstance(raw, dict):
        items = raw.get("overlays", raw.get("items", []))
        end_card, label = raw.get("end_card"), raw.get("label")
    else:
        die("Plan must be a JSON list or an object with an 'overlays' list.")

    clean = []
    for i, it in enumerate(items, 1):
        where = "overlay #%d" % i
        try:
            start, end = float(it["start"]), float(it["end"])
            text = str(it["text"]).strip()
        except (KeyError, TypeError, ValueError):
            die("%s: needs numeric 'start', 'end' and a 'text'." % where)
        if not text:
            die("%s: empty text." % where)
        if start < 0 or end <= start:
            die("%s: need 0 <= start < end (got %s..%s)." % (where, start, end))
        if start >= duration:
            warn("%s starts at %.2fs, after the end of the video (%.2fs) - skipped." % (where, start, duration))
            continue
        if end > duration:
            warn("%s ends at %.2fs, video is %.2fs long - clamped." % (where, end, duration))
            end = duration
        pos = str(it.get("position", "bottom")).lower()
        if pos not in ("top", "center", "bottom"):
            die("%s: position must be top, center or bottom (got %r)." % (where, pos))
        style = str(it.get("style", DEFAULT_STYLE)).lower()
        if style not in STYLES:
            die("%s: unknown style %r. Available: %s" % (where, style, ", ".join(STYLES)))
        clean.append(dict(start=start, end=end, text=text, position=pos, style=style,
                          size=it.get("size"), color=it.get("color"),
                          upper=bool(it.get("upper", True)),
                          fade=float(it.get("fade", FADE))))
    # overlap warning for same position
    for a in range(len(clean)):
        for b in range(a + 1, len(clean)):
            x, y = clean[a], clean[b]
            if x["position"] == y["position"] and x["start"] < y["end"] - 0.05 and y["start"] < x["end"] - 0.05:
                warn("overlays %r and %r overlap in time at position %s." % (x["text"], y["text"], x["position"]))
    return clean, end_card, label


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Burn captions / label / end card into a vertical video.")
    ap.add_argument("input")
    ap.add_argument("plan")
    ap.add_argument("output")
    ap.add_argument("--lang", choices=["ru", "kk"], default="ru",
                    help="language of the corner label (default ru)")
    ap.add_argument("--label", action="store_true",
                    help="show the corner label 'Визуализация (ИИ)' / '(AI)' for the whole clip")
    ap.add_argument("--label-text", help="custom text for the corner label")
    ap.add_argument("--end-card", help="end card CTA text (overrides the plan)")
    ap.add_argument("--end-card-seconds", type=float, help="end card length (default 2.5)")
    ap.add_argument("--font", help="path to a bold .ttf/.otf font with Cyrillic")
    ap.add_argument("--crf", type=int, default=18, help="x264 quality, lower = better (default 18)")
    ap.add_argument("--keep-temp", action="store_true", help="keep temporary PNG/filter files")
    ap.add_argument("--dry-run", action="store_true", help="only print the ffmpeg command")
    a = ap.parse_args()

    need_tool("ffmpeg")
    need_tool("ffprobe")
    if not os.path.isfile(a.input):
        die("Input video not found: %s" % a.input)
    if os.path.abspath(a.input) == os.path.abspath(a.output):
        die("Output must be a different file than the input.")

    info = probe(a.input)
    dur = info["duration"]
    if info["h"] <= info["w"]:
        warn("Input is not vertical (%dx%d). It will be cropped to 9:16." % (info["w"], info["h"]))
    elif abs(info["w"] / info["h"] - 9 / 16) > 0.02:
        warn("Input aspect is %dx%d, not 9:16. Edges will be cropped to fill 1080x1920." % (info["w"], info["h"]))

    items, plan_end, plan_label = load_plan(a.plan, dur)
    fonts = Fonts(find_font(a.font))

    # --- end card spec
    end_text = a.end_card
    end_sub = None
    end_secs = a.end_card_seconds
    if isinstance(plan_end, str):
        end_text = end_text or plan_end
    elif isinstance(plan_end, dict):
        end_text = end_text or plan_end.get("text")
        end_sub = plan_end.get("subtext")
        end_secs = end_secs or plan_end.get("seconds")
    end_secs = float(end_secs or 2.5)
    if end_text and end_secs >= dur:
        die("End card (%.1fs) is longer than the video (%.1fs)." % (end_secs, dur))

    # --- label spec
    label_text = None
    if a.label or a.label_text or plan_label:
        label_text = a.label_text or (plan_label if isinstance(plan_label, str) else LABELS[a.lang])

    # --- glyph check
    all_text = "".join(i["text"] for i in items) + (end_text or "") + (end_sub or "") + (label_text or "")
    miss = fonts.missing_glyphs(all_text)
    if miss:
        warn("Font %s has no glyphs for: %s  (they will look like empty boxes)"
             % (os.path.basename(fonts.path), " ".join(miss)))

    tmp = tempfile.mkdtemp(prefix="overlay_")
    try:
        inputs = []     # (png_path, end_time)
        chains = []     # filter fragments
        # base video: cover-scale to 1080x1920, 30 fps
        chains.append(
            "[0:v]scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=%d:%d,setsar=1,fps=%d,format=yuv420p[v0]" % (W, H, W, H, FPS))
        last = "v0"
        n = 0

        def add_overlay(png, x, y, start, end, fade_in, fade_out):
            """Register a PNG as ffmpeg input #k and chain an overlay."""
            nonlocal last, n
            n += 1
            idx = len(inputs) + 1
            inputs.append((png, end))
            frag = "[%d:v]format=rgba" % idx
            if fade_in > 0:
                frag += ",fade=t=in:st=%.3f:d=%.3f:alpha=1" % (start, fade_in)
            if fade_out > 0:
                frag += ",fade=t=out:st=%.3f:d=%.3f:alpha=1" % (end - fade_out, fade_out)
            frag += "[o%d]" % n
            chains.append(frag)
            en = "enable='between(t,%.3f,%.3f)'" % (start, end) if start is not None else ""
            chains.append("[%s][o%d]overlay=%d:%d:format=auto:eof_action=pass%s[v%d]"
                          % (last, n, x, y, ("" if not en else ":" + en), n))
            last = "v%d" % n

        # corner label (whole clip, short fade-in)
        if label_text:
            img = render_label(label_text, fonts)
            p = os.path.join(tmp, "label.png")
            img.save(p)
            add_overlay(p, 36, SAFE_TOP + 14, 0.0, dur, 0.4, 0)

        # captions
        for k, it in enumerate(items, 1):
            text = it["text"].upper() if it["upper"] else it["text"]
            img, box = render_caption(text, fonts, STYLES[it["style"]],
                                      it["size"], it["color"])
            shadow_pad = box[0]
            inner_h = box[3] - box[1]
            y = place_y(it["position"], inner_h, box[1])
            x = (W - img.width) // 2
            p = os.path.join(tmp, "cap%02d.png" % k)
            img.save(p)
            fd = min(it["fade"], (it["end"] - it["start"]) / 3.0)
            add_overlay(p, x, y, it["start"], it["end"], fd, fd)

        # end card
        if end_text:
            img = render_end_card(end_text.upper(), end_sub.upper() if end_sub else None, fonts)
            p = os.path.join(tmp, "endcard.png")
            img.save(p)
            s = dur - end_secs
            add_overlay(p, 0, 0, s, dur, 0.45, 0)

        chains.append("[%s]format=yuv420p[vout]" % last)
        script = os.path.join(tmp, "filters.txt")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(";\n".join(chains))

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", a.input]
        for png, end in inputs:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % (end + 0.1), "-i", png]
        if not info["audio"]:
            cmd += ["-f", "lavfi", "-t", "%.3f" % dur, "-i", "anullsrc=r=48000:cl=stereo"]
            audio_map = ["-map", "%d:a" % (len(inputs) + 1)]
            audio_filter = []
        else:
            audio_map = ["-map", "0:a:0"]
            audio_filter = ["-af", "aresample=48000:async=1:first_pts=0,apad"]
        cmd += ["-filter_complex_script", script, "-map", "[vout]"] + audio_map + audio_filter
        cmd += ["-t", "%.3f" % dur,
                "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1",
                "-preset", "medium", "-crf", str(a.crf),
                "-maxrate", "12M", "-bufsize", "24M",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60", "-bf", "2",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", "-map_metadata", "-1",
                a.output]

        if a.dry_run:
            print(" ".join(repr(c) if " " in c else c for c in cmd))
            print("\n--- filters.txt ---\n" + open(script, encoding="utf-8").read())
            a.keep_temp = True
            print("\ntemp dir: " + tmp)
            return
        print("Rendering %d caption(s)%s%s on %s (%.2fs) ..." % (
            len(items), ", label" if label_text else "", ", end card" if end_text else "",
            os.path.basename(a.input), dur))
        r = subprocess.run(cmd)
        if r.returncode != 0:
            die("ffmpeg failed (see the message above). Re-run with --keep-temp to inspect files.")
        print("Done: %s" % a.output)
    finally:
        if a.keep_temp:
            print("Temp files kept in: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
