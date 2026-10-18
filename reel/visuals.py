"""Visual providers. Each returns (path, kind) where kind is 'image' or 'video', or None on failure.

* pollinations - free AI stills (no key). Rendered with a slow Ken Burns move.
* pexels       - free stock *video* (needs a free PEXELS_API_KEY secret).

True AI video models (Wan 2.2 / LTX-Video) need a GPU, which GitHub's free runners do not have.
Add one as a new provider function if you run this on your own GPU machine.
"""
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests


def _pollinations(prompt: str, out: Path, seed: int):
    url = (
        "https://image.pollinations.ai/prompt/" + quote(prompt[:900])
        + f"?width=864&height=1536&seed={seed}&model=flux&nologo=true"
    )
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=150)
            if r.ok and r.headers.get("content-type", "").startswith("image") and len(r.content) > 5000:
                out.write_bytes(r.content)
                return out, "image"
        except requests.RequestException:
            pass
        time.sleep(6 * (attempt + 1))
    return None


def _pexels(query: str, out: Path, index: int):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        print("::warning::PEXELS_API_KEY secret not set; falling back to AI stills.")
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait", "per_page": 10},
            timeout=30,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        for k in range(len(videos)):
            v = videos[(index + k) % len(videos)]
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("height", 0) >= 1280]
            if not files:
                continue
            best = min(files, key=lambda f: f["height"])
            data = requests.get(best["link"], timeout=180)
            data.raise_for_status()
            out.write_bytes(data.content)
            return out, "video"
    except requests.RequestException as exc:
        print(f"::warning::Pexels failed: {exc}")
    return None


def get_visual(provider: str, shot: dict, index: int, work: Path, plan: dict, seed: int):
    full_prompt = f"{shot['prompt']}. {plan['character_sheet']}. {plan['style']}"
    if provider == "pexels":
        got = _pexels(shot["stock_query"], work / f"shot{index}.mp4", index)
        if got:
            return got
    return _pollinations(full_prompt, work / f"shot{index}.jpg", seed)
