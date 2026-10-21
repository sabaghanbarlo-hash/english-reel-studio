"""Offline smoke test: renders a full stickman reel with a silent mock voice (no network, no API keys).

    python scripts/test_render.py            # writes out/reel.mp4
    python scripts/test_render.py --keep     # keep the work/ folder too

Checks that the planner, stickman renderer, subtitles and final mix all work together.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["TTS_MOCK"] = "1"
os.environ.pop("GITHUB_TOKEN", None)  # force the offline keyword planner

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

SCRIPT = (
    "Your brain hates unfinished things. "
    "Psychologists call it the Zeigarnik effect: open tasks keep nagging at your mind until you close them. "
    "That is why you replay an argument at 2 a.m. "
    "The fix is surprisingly simple. "
    "Write down exactly what is unresolved, and the next step you will take. "
    "Your mind relaxes once it trusts there is a plan. "
    "What is the one thing you keep carrying around?"
)

from reel import run  # noqa: E402

os.environ["SCRIPT"] = SCRIPT
run.main()

reel = ROOT / "out" / "reel.mp4"
info = subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
     "-of", "default=nw=1", str(reel)], text=True)
print(info)
assert reel.stat().st_size > 50_000, "reel.mp4 is suspiciously small"
assert "width=1080" in info and "height=1920" in info, "wrong resolution"
assert "codec_type=audio" in info and "codec_type=video" in info, "missing audio or video stream"
if "--keep" not in sys.argv:
    shutil.rmtree(ROOT / "work", ignore_errors=True)
print("OK:", reel)
