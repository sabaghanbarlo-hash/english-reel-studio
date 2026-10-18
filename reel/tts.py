"""Free Persian text-to-speech via Microsoft Edge voices (edge-tts >= 7, no API key), with word timings.

The fa-IR voices have no emotion styles, so delivery is shaped per sentence with rate, pitch and volume.
"""
import asyncio

import edge_tts

VOICES = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}
DELIVERY = {  # (rate, pitch, volume)
    "hook": ("-8%", "-4Hz", "+0%"),
    "tense": ("-3%", "-2Hz", "+4%"),
    "calm": ("-6%", "-1Hz", "-2%"),
    "warm": ("-8%", "+1Hz", "-4%"),
    "reflective": ("-11%", "-3Hz", "-6%"),
}
DEFAULT = ("-6%", "+0Hz", "+0%")


def prosody(delivery):
    return DELIVERY.get(delivery or "", DEFAULT)


async def _stream(text, voice, rate, pitch, volume, out):
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


def synth_with_timing(text, voice, delivery, out):
    """Synthesise one sentence. Returns [(start_s, duration_s)] per spoken word."""
    rate, pitch, volume = prosody(delivery)
    last = None
    for _ in range(3):
        try:
            return asyncio.run(_stream(text, voice, rate, pitch, volume, str(out)))
        except Exception as exc:  # transient websocket errors happen
            last = exc
    raise SystemExit(f"TTS failed after 3 attempts: {last}")
