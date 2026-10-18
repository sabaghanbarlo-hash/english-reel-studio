"""Typewriter subtitles: each word appears exactly when the voice says it (ASS, RTL-safe, clear of Instagram UI)."""
import re

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Vazirmatn,64,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,120,150,470,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

RLM = "\u200f"
_END = re.compile(r"[.!\u061f?\u2026]$")
_TRAIL = re.compile(r"[\u00bb\"')\]]+$")
HIDE, SHOW = "{\\alpha&HFF&}", "{\\alpha&H00&}"


def _t(sec):
    cs = int(round(max(0.0, sec) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def cues(words, max_chars=34, pause=0.45):
    out, cur = [], []
    for w in words:
        if cur:
            joined = " ".join(x["shown"] for x in cur + [w])
            ended = bool(_END.search(_TRAIL.sub("", cur[-1]["shown"])))
            if len(joined) > max_chars or w["start"] - cur[-1]["end"] > pause or ended:
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _split(shown, line_max=20):
    if len(" ".join(shown)) <= line_max or len(shown) < 2:
        return len(shown)
    return min(range(1, len(shown)), key=lambda i: abs(len(" ".join(shown[:i])) - len(" ".join(shown[i:]))))


def _text(cue, visible):
    shown = [w["shown"].replace("{", "").replace("}", "") for w in cue]
    marked = [wd if i < visible else HIDE + wd + SHOW for i, wd in enumerate(shown)]
    cut = _split(shown)
    if cut >= len(shown):
        return RLM + " ".join(marked)
    return RLM + " ".join(marked[:cut]) + "\\N" + RLM + " ".join(marked[cut:])


def build(words):
    """Fixed layout per cue; words not yet spoken are transparent, so nothing jumps around."""
    lines = [HEADER]
    cs = cues(words)
    for ci, cue in enumerate(cs):
        end = cue[-1]["end"] + 0.35
        if ci + 1 < len(cs):
            end = min(end, cs[ci + 1][0]["start"] - 0.03)
        end = max(end, cue[-1]["start"] + 0.2)
        for k, w in enumerate(cue):
            t0 = max(0.0, w["start"] - 0.04)
            t1 = cue[k + 1]["start"] - 0.04 if k + 1 < len(cue) else end
            if t1 <= t0:
                t1 = t0 + 0.05
            lines.append(f"Dialogue: 0,{_t(t0)},{_t(t1)},Main,,0,0,0,,{_text(cue, k + 1)}\n")
    return "".join(lines)
