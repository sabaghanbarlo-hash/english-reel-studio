"""Free English text-to-speech via Microsoft Edge neural voices (edge-tts >= 7, no API key), with word timings.

Edge voices have no emotion styles through this API, so delivery is shaped per sentence with rate, pitch and volume.

Set TTS_MOCK=1 to skip the network: silent audio plus estimated word timings. Used by scripts/test_render.py so
the stickman renderer can be tested anywhere.
"""
import asyncio
import os
import subprocess

VOICES = {"male": "en-US-AndrewNeural", "female": "en-US-AvaNeural"}
DELIVERY = {  # (rate, pitch, volume)
    "hook": ("+0%", "-2Hz", "+4%"),
    "tense": ("+2%", "-1Hz", "+4%"),
    "calm": ("-2%", "+0Hz", "+0%"),
    "warm": ("-4%", "+1Hz", "-2%"),
    "reflective": ("-7%", "-2Hz", "-4%"),
}
DEFAULT = ("-2%", "+0Hz", "+0%")


def prosody(delivery):
    return DELIVERY.get(delivery or "", DEFAULT)


async def _stream(text, voice, rate, pitch, volume, out):
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary")
    audio, words = bytearray(), []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            words.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7))
    if not audio:
        raise RuntimeError("no audio received")
    with open(out, "wb") as f:
        f.write(bytes(audio))
    return words


def _mock(text, out):
    """Silent clip with plausible word timings (roughly 2.7 words per second)."""
    t, events = 0.15, []
    for w in text.split():
        d = 0.12 + 0.045 * len(w.strip(".,!?;:\"'"))
        events.append((t, d))
        t += d + 0.06
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", f"{t + 0.2:.3f}", "-q:a", "9", str(out)], check=True)
    return events


def synth_with_timing(text, voice, delivery, out):
    """Synthesise one sentence. Returns [(start_s, duration_s)] per spoken word."""
    if os.environ.get("TTS_MOCK"):
        return _mock(text, out)
    rate, pitch, volume = prosody(delivery)
    last = None
    for _ in range(3):
        try:
            return asyncio.run(_stream(text, voice, rate, pitch, volume, str(out)))
        except Exception as exc:  # transient websocket errors happen
            last = exc
    raise SystemExit(f"TTS failed after 3 attempts: {last}")
