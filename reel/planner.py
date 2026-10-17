"""Turn a pasted Persian script into a shot plan: narration slices + English visual prompts.

Input can be:
  * plain Persian narration  -> split into shots by GitHub Models (free with the Actions token),
                                falling back to a simple sentence splitter
  * a JSON object            -> used as-is (full manual control), see README
"""
import json
import os
import re

import requests

MODELS_URL = "https://models.github.ai/inference/chat/completions"
MODEL = os.environ.get("PLANNER_MODEL", "openai/gpt-4.1-mini")

DEFAULT_STYLE = (
    "realistic cinematic film still, 35mm, shallow depth of field, soft natural light, "
    "muted teal and warm tones, vertical 9:16, no text, no logos, no watermark"
)
FALLBACK_CHARACTER = (
    "a fictional Iranian woman in her late 20s with shoulder-length dark wavy hair and a cream knit "
    "sweater, in a modern apartment with warm lamp light"
)

SYSTEM = """You are the shot planner for a faceless Persian Instagram account about relationship psychology.
Split the user's Persian narration into 4-7 consecutive shots for a vertical 9:16 reel.
Return ONLY a JSON object with exactly these keys:
{
 "character_sheet": "ONE fixed English description of the recurring fictional characters (age, hair, clothing) and the setting, reused in every shot for consistency",
 "shots": [{"narration": "...", "prompt": "...", "stock_query": "..."}],
 "caption": "short Persian caption, max 2 lines",
 "hashtags": ["#..."],
 "pinned_question": "one thoughtful Persian question that invites discussion"
}
Rules:
- The narration values, concatenated in order, must reproduce the user's text EXACTLY. Never rewrite, add or remove words; only choose where to cut.
- Each prompt: detailed English cinematic description (subject, emotion, setting, lighting, camera movement). Realistic, original fictional people, no celebrities, no visible text, signs or logos.
- stock_query: 2-4 English words for a stock-footage search.
- 5-8 relevant Persian hashtags. Do not invent statistics, studies or quotes."""


def clean(text: str) -> str:
    text = re.sub(r"\(\s*(CTA|cta)\s*\)", "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _normalize(data: dict, source: str) -> dict:
    shots = []
    for s in data.get("shots", []):
        narration = clean(str(s.get("narration", "")))
        if not narration:
            continue
        shots.append({
            "narration": narration,
            "prompt": str(s.get("prompt", "")).strip() or "quiet emotional moment, cinematic",
            "stock_query": str(s.get("stock_query", "")).strip() or "person thinking window",
        })
    if not shots:
        raise SystemExit("No shots with narration found in the input.")
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    return {
        "source": source,
        "character_sheet": str(data.get("character_sheet") or FALLBACK_CHARACTER).strip(),
        "style": str(data.get("style") or DEFAULT_STYLE).strip(),
        "shots": shots,
        "caption": str(data.get("caption") or "").strip(),
        "hashtags": [t if t.startswith("#") else "#" + t for t in tags],
        "pinned_question": str(data.get("pinned_question") or "").strip(),
    }


def _llm(script: str):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    try:
        r = requests.post(
            MODELS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "temperature": 0.4,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": script},
                ],
            },
            timeout=120,
        )
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        content = (r.json()["choices"][0]["message"].get("content") or "").strip()
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise RuntimeError(f"no JSON in reply: {content[:200]!r}")
        data = json.loads(m.group(0))
        joined = "".join(str(s.get("narration", "")) for s in data["shots"])
        if _norm(joined) != _norm(script):
            print("::warning::Planner changed the narration text; discarding that plan.")
            return None
        if not 1 <= len(data["shots"]) <= 8:
            return None
        return _normalize(data, "llm")
    except Exception as exc:  # network, quota, bad JSON ...
        print(f"::warning::Shot planner call failed: {exc}")
        return None


def _fallback(script: str, n: int = 5) -> dict:
    sentences = [s.strip() for s in re.split(r"(?<=[.!\u061f?\u2026])\s+", script) if s.strip()] or [script]
    n = max(1, min(n, len(sentences)))
    size = -(-len(sentences) // n)
    groups = [" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size)]
    moods = [
        "close-up, tense and hurt expression",
        "medium shot, emotional distance between two people",
        "close-up, overwhelmed expression, shallow breathing",
        "calm moment by a window, slow deep breath",
        "warm reconciliation, soft smile",
    ]
    shots = [
        {"narration": g, "prompt": moods[i % len(moods)], "stock_query": "person thinking window"}
        for i, g in enumerate(groups)
    ]
    return _normalize({"shots": shots}, "fallback")


def plan(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        return _normalize(json.loads(raw), "manual")
    script = clean(raw)
    if not script:
        raise SystemExit("The script is empty.")
    for _ in range(2):
        result = _llm(script)
        if result:
            return result
    print("::warning::AI shot planner unavailable - using generic prompts. Paste a JSON shot list for full control.")
    return _fallback(script)


def hook_line(shots: list) -> str:
    first = re.split(r"(?<=[.!\u061f?\u2026])\s+", shots[0]["narration"])[0]
    return first[:150].strip()
