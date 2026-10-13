"""Persian subtitles as an ASS file (libass shapes RTL text). Kept clear of Instagram's UI zones."""

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


def _t(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def chunk(text: str, max_chars: int = 34) -> list:
    cues, cur = [], []
    for w in text.split():
        if cur and len(" ".join(cur + [w])) > max_chars:
            cues.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        cues.append(cur)
    return cues


def _two_lines(words: list, line_max: int = 20) -> str:
    joined = " ".join(words)
    if len(joined) <= line_max or len(words) < 2:
        return RLM + joined
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return RLM + " ".join(words[:best]) + "\\N" + RLM + " ".join(words[best:])


def build(shots: list, starts: list, audio_durs: list) -> str:
    lines = [HEADER]
    for shot, t0, ad in zip(shots, starts, audio_durs):
        cues = chunk(shot["narration"])
        weights = [max(1, len(" ".join(c))) for c in cues]
        total = sum(weights)
        span = max(0.5, ad - 0.05)
        t = t0 + 0.05
        for cue, w in zip(cues, weights):
            d = span * w / total
            lines.append(f"Dialogue: 0,{_t(t)},{_t(t + d)},Main,,0,0,0,,{_two_lines(cue)}\n")
            t += d
    return "".join(lines)
