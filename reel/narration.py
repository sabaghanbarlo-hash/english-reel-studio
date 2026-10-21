"""Narration with real timing.

Whole sentences are synthesised in one go (a voice sounds far more natural than when it is cut into
3-second pieces, each with its own falling 'end of sentence' tone). Word timestamps from the voice then
drive both the scene changes, the stickman's mouth and the word-by-word subtitles, so everything stays in sync.
"""
import re

from . import render, tts

_END = re.compile(r"[.!?…]$")
_TRAIL = re.compile(r"[”’\"')\]]+$")
_PUNCT_ONLY = re.compile(r"^[\W_]+$")
LEAD = 0.08   # the picture changes just before the first word of a shot
TAIL = 0.9    # silence after the last word


def tokens(text):
    out = []
    for t in text.split():
        if out and _PUNCT_ONLY.match(t):
            out[-1] += t
        else:
            out.append(t)
    return out


def sentence_end(tok):
    return bool(_END.search(_TRAIL.sub("", tok)))


def _gap_after(tok):
    t = _TRAIL.sub("", tok)
    if t.endswith("…"):
        return 0.8
    if t.endswith("?"):
        return 0.55
    return 0.6


def _words(shots):
    words = []
    for i, s in enumerate(shots):
        shown = tokens(s["narration"])
        spoken = tokens(s.get("spoken") or s["narration"])
        if len(spoken) != len(shown):
            spoken = shown
        for a, b in zip(shown, spoken):
            words.append({"shot": i, "shown": a, "spoken": b})
    return words


def _units(words):
    units, cur = [], []
    for k, w in enumerate(words):
        cur.append(k)
        if sentence_end(w["spoken"]) or len(cur) >= 30:
            units.append(cur)
            cur = []
    if cur:
        units.append(cur)
    return units


def build(plan, voice, work):
    shots = plan["shots"]
    words = _words(shots)
    units = _units(words)
    parts, t = [], 0.0
    for u, idxs in enumerate(units):
        text = " ".join(words[k]["spoken"] for k in idxs)
        delivery = shots[words[idxs[0]]["shot"]].get("delivery")
        mp3, wav = work / f"unit{u}.mp3", work / f"unit{u}.wav"
        events = tts.synth_with_timing(text, voice, delivery, mp3)
        render.run(["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "2", wav])
        dur = render.duration(wav)
        n = len(idxs)
        if len(events) == n:
            times = [(t + s, t + s + d) for s, d in events]
        else:  # voice split words differently: spread by character count inside the sentence
            print(f"::warning::sentence {u + 1}: {len(events)} timings for {n} words; spreading by length.")
            first = events[0][0] if events else 0.1
            lens = [max(1, len(words[k]["spoken"])) for k in idxs]
            span = max(0.3, dur - first - 0.15)
            times, pos = [], first
            for ln in lens:
                w = span * ln / sum(lens)
                times.append((t + pos, t + pos + w))
                pos += w
        for k, (s, e) in zip(idxs, times):
            words[k]["start"], words[k]["end"] = s, e
        parts.append(wav)
        t += dur
        last = u == len(units) - 1
        gap = TAIL if last else _gap_after(words[idxs[-1]]["spoken"])
        if u == 0 and not last:
            gap += 0.3            # let the hook land
        if u == len(units) - 2:
            gap += 0.25           # breathe before the closing line
        sil = work / f"gap{u}.wav"
        render.silence(gap, sil)
        parts.append(sil)
        t += render.duration(sil)
    wav_all = work / "narration.wav"
    render.concat_audio(parts, wav_all)
    total = t

    first_word = {}
    for k, w in enumerate(words):
        first_word.setdefault(w["shot"], k)
    starts = [0.0]
    for i in range(1, len(shots)):
        starts.append(max(starts[-1] + 1.2, words[first_word[i]]["start"] - LEAD))
    starts.append(total)
    durs = [starts[i + 1] - starts[i] for i in range(len(shots))]
    if min(durs) < 0.8:  # pathological timing: fall back to an even split by word count
        counts = [sum(1 for w in words if w["shot"] == i) or 1 for i in range(len(shots))]
        durs = [total * c / sum(counts) for c in counts]
    return {"wav": wav_all, "total": total, "shot_durs": durs, "words": words}
