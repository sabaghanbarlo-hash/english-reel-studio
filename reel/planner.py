"""Turn a pasted Persian script into a shot plan: narration slices, TTS text, delivery, English visual prompts.

Input can be plain Persian narration (planned by an LLM, with a safe offline fallback) or a JSON object.
The LLM may only choose where to cut: the narration must come back word-for-word, otherwise the plan is discarded.
"""
import json
import os
import re
import time

import requests

MODELS_URL = "https://models.github.ai/inference/chat/completions"
MODEL = os.environ.get("PLANNER_MODEL", "openai/gpt-4.1-mini")
DELIVERIES = ("hook", "tense", "calm", "warm", "reflective")

DEFAULT_STYLE = (
    "photorealistic cinematic film still, 35mm, anamorphic lens, shallow depth of field, soft film grain, "
    "moody teal and warm amber colour grade, no faces, no text, no watermark"
)
FALLBACK_CHARACTER = (
    "a quiet modern apartment at night, warm lamp light against cool blue shadows, one consistent muted teal-and-amber palette"
)
SCENES = [
    "an empty chair beside a rain-streaked window at night, warm lamp glow, no people",
    "two tea cups on a wooden table, steam rising, soft window light, no people",
    "close-up of a person's hands nervously clasped on their lap, shallow depth of field, faces out of frame",
    "silhouette of a person standing at a balcony door, blurred city lights behind, back to camera",
    "a phone lying face-down on a table in a dim room, cool light from a window",
    "a half-open door with warm light spilling into a dark hallway, no people",
    "rain running down a window with blurred city lights, moody and quiet",
    "two long shadows on a living-room wall in evening light, no faces visible",
]

SYSTEM = """You are the shot planner for a faceless Persian Instagram account about relationship psychology.
Split the user's Persian narration into 6-12 consecutive shots for a vertical 9:16 reel. Each shot's narration is one short phrase or sentence (about 3 seconds spoken, 6-14 words) so the picture changes every few seconds.
Return ONLY a JSON object:
{"character_sheet": "...", "shots": [{"narration": "...", "spoken": "...", "delivery": "...", "prompt": "...", "stock_query": "..."}], "caption": "...", "hashtags": ["#..."], "pinned_question": "..."}
Rules:
- narration values concatenated in order must reproduce the user's text EXACTLY (only choose where to cut).
- spoken: the same words in the same order, lightly prepared for a text-to-speech voice: add commas or ellipses where a human would pause. Never add, drop or change words.
- delivery: one of hook, tense, calm, warm, reflective.
- NEVER show faces. Use silhouettes, backs of heads, hands, over-the-shoulder views, shadows on walls, and objects or places (phone face-down on a table, two tea cups, an empty chair, a half-open door, rain on a window, city lights at night). One consistent location, time of day and colour palette across all shots; describe them once in character_sheet.
- prompt: English, max 60 words: subject, composition, light, lens, mood. Photorealistic cinematic still. No text, signs or logos. No celebrities.
- stock_query: 2-4 English words.
- caption: short Persian caption. hashtags: 5-8 Persian. pinned_question: one thoughtful Persian question. Never invent statistics, studies or quotes."""

_PUNCT = re.compile(r"[\s\.,\u060c\u061b\u2026!\u061f\?\u200c:;\"\u00ab\u00bb\-\u2014()]+")


def clean(text: str) -> str:
    text = re.sub(r"\(\s*(CTA|cta)\s*\)", "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip(s: str) -> str:
    return _PUNCT.sub("", s)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _spoken(narration: str, spoken) -> str:
    spoken = clean(str(spoken or ""))
    return spoken if spoken and _strip(spoken) == _strip(narration) else narration


def _normalize(data: dict, source: str) -> dict:
    shots = []
    for s in data.get("shots", []):
        narration = clean(str(s.get("narration", "")))
        if not narration:
            continue
        delivery = str(s.get("delivery", "")).strip().lower()
        shots.append({
            "narration": narration,
            "spoken": _spoken(narration, s.get("spoken")),
            "delivery": delivery if delivery in DELIVERIES else "calm",
            "prompt": str(s.get("prompt", "")).strip() or SCENES[len(shots) % len(SCENES)],
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


_ENDPOINTS = (
    (MODELS_URL, MODEL),
    ("https://models.inference.ai.azure.com/chat/completions", "gpt-4o-mini"),
)


def _chat_github(system: str, user: str):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    for url, model in _ENDPOINTS:
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
                json={"model": model, "temperature": 0.4, "max_tokens": 6000,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                timeout=120,
            )
            ctype = r.headers.get("content-type", "")
            if r.ok and "json" in ctype:
                content = r.json()["choices"][0]["message"].get("content") or ""
                if content:
                    return content
            print(f"::warning::{url}: HTTP {r.status_code} {ctype} body={r.text[:300]!r}")
        except Exception as exc:
            print(f"::warning::{url} failed: {exc!r}")
    return None


def _chat_pollinations(system: str, user: str):
    # Keyless fallback. Anonymous tier allows 1 reply per 30 s, so wait and retry on HTTP 402.
    for _ in range(3):
        try:
            r = requests.post(
                "https://text.pollinations.ai/openai",
                json={"model": "openai", "temperature": 0.4, "max_tokens": 6000, "reasoning_effort": "low",
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                timeout=180,
            )
            if r.status_code == 402:
                time.sleep(32)
                continue
            if not r.ok:
                print(f"::warning::Pollinations text: HTTP {r.status_code} {r.text[:200]!r}")
                return None
            choice = r.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                print("::warning::Pollinations text: reply was cut off (token limit).")
            return choice["message"].get("content") or ""
        except Exception as exc:
            print(f"::warning::Pollinations text call failed: {exc!r}")
            return None
    return None


def _plan_llm(script: str):
    for name, chat in (("github-models", _chat_github), ("pollinations", _chat_pollinations)):
        content = chat(SYSTEM, script)
        m = re.search(r"\{.*\}", content or "", re.S)
        if not m:
            continue
        try:
            data = json.loads(m.group(0))
            shots = data["shots"]
            if not 3 <= len(shots) <= 14:
                print(f"::warning::{name}: {len(shots)} shots is outside 3-14; discarding.")
                continue
            if _norm("".join(str(s.get("narration", "")) for s in shots)) != _norm(script):
                print(f"::warning::{name} changed the narration text; discarding that plan.")
                continue
            return _normalize(data, name)
        except Exception as exc:
            print(f"::warning::{name}: unusable reply ({exc!r}).")
    return None


def _clauses(script: str) -> list:
    out = []
    for sent in (s.strip() for s in re.split(r"(?<=[.!\u061f?\u2026:])\s+", script) if s.strip()):
        if len(sent.split()) <= 14:
            out.append(sent)
            continue
        buf = ""
        for part in re.split(r"(?<=[\u060c,])\s+", sent):
            buf = (buf + " " + part).strip()
            if len(buf.split()) >= 6:
                out.append(buf)
                buf = ""
        if buf:
            if out and len(buf.split()) < 3:
                out[-1] += " " + buf
            else:
                out.append(buf)
    merged = []
    for c in out:
        if merged and len(c.split()) < 4:
            merged[-1] += " " + c
        else:
            merged.append(c)
    if len(merged) > 12:
        size = -(-len(merged) // 12)
        merged = [" ".join(merged[i:i + size]) for i in range(0, len(merged), size)]
    return merged or [script]


def _fallback(script: str) -> dict:
    parts = _clauses(script)
    shots = []
    for i, p in enumerate(parts):
        delivery = "hook" if i == 0 else "warm" if i == len(parts) - 1 else ("tense" if i % 3 == 1 else "calm")
        shots.append({"narration": p, "delivery": delivery, "prompt": SCENES[i % len(SCENES)],
                      "stock_query": "empty room window rain"})
    return _normalize({"shots": shots}, "fallback")


def plan(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        return _normalize(json.loads(raw), "manual")
    script = clean(raw)
    if not script:
        raise SystemExit("The script is empty.")
    result = _plan_llm(script)
    if result:
        return result
    print("::warning::No AI planner reachable - using the built-in faceless scene set. Paste a JSON shot list for full control.")
    return _fallback(script)


def hook_line(shots: list) -> str:
    first = re.split(r"(?<=[.!\u061f?\u2026])\s+", shots[0]["narration"])[0]
    return first[:150].strip()
