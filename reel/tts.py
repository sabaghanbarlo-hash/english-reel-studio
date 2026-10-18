"""Free Persian text-to-speech via Microsoft Edge voices (edge-tts, no API key).

The fa-IR voices have no emotion styles, so delivery is shaped with speaking rate and pitch per shot.
"""
import asyncio

import edge_tts

VOICES = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}
DELIVERY = {  # (rate, pitch)
    "hook": ("-6%", "-3Hz"),
    "tense": ("-2%", "-2Hz"),
    "calm": ("-4%", "+0Hz"),
    "warm": ("-6%", "+2Hz"),
    "reflective": ("-9%", "-2Hz"),
}


async def _save(text: str, voice: str, rate: str, pitch: str, out: str) -> None:
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(out)


def synth(text: str, voice: str, out, delivery=None) -> None:
    rate, pitch = DELIVERY.get(delivery or "", ("-4%", "+0Hz"))
    last = None
    for _ in range(3):
        try:
            asyncio.run(_save(text, voice, rate, pitch, str(out)))
            return
        except Exception as exc:  # transient websocket errors happen
            last = exc
    raise SystemExit(f"TTS failed after 3 attempts: {last}")
