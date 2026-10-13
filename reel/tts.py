"""Free Persian text-to-speech via Microsoft Edge voices (edge-tts, no API key)."""
import asyncio

import edge_tts

VOICES = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}


async def _save(text: str, voice: str, rate: str, out: str) -> None:
    await edge_tts.Communicate(text, voice, rate=rate).save(out)


def synth(text: str, voice: str, out, rate: str = "-4%") -> None:
    last = None
    for _ in range(3):
        try:
            asyncio.run(_save(text, voice, rate, str(out)))
            return
        except Exception as exc:  # transient websocket errors happen
            last = exc
    raise SystemExit(f"TTS failed after 3 attempts: {last}")
