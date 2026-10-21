"""Turn a pasted English script into a scene plan for the stickman explainer.

Input can be plain English narration (planned by an LLM, with a safe offline fallback) or a JSON object.
The LLM may only choose where to cut and which prop / pose / emotion each scene gets: the narration must
come back word-for-word, otherwise the plan is discarded and a plain sentence splitter is used.
"""
import json
import os
import re
import time

import requests

from .vocab import EMOTIONS, NEUTRAL, POSES, PROPS, emotion_for, guess_prop

MODELS_URL = "https://models.github.ai/inference/chat/completions"
MODEL = os.environ.get("PLANNER_MODEL", "openai/gpt-4.1-mini")
DELIVERIES = ("hook", "tense", "calm", "warm", "reflective")

SYSTEM = f"""You are the scene planner for a faceless Instagram account that explains psychology with an animated stickman.
Split the user's English narration into 6-10 consecutive scenes for a vertical 9:16 reel. Each scene's narration is one short phrase or sentence (about 3 seconds spoken, 6-14 words) so the picture changes every few seconds.
Return ONLY a JSON object:
{{"shots": [{{"narration": "...", "spoken": "...", "delivery": "...", "scene": "...", "pose": "...", "emotion": "...", "label": "..."}}], "caption": "...", "hashtags": ["#..."], "pinned_question": "..."}}
Rules:
- narration values concatenated in order must reproduce the user's text EXACTLY (only choose where to cut).
- spoken: the same words in the same order, lightly prepared for a text-to-speech voice: add commas or ellipses where a human would pause. Never add, drop or change words.
- delivery: one of {", ".join(DELIVERIES)}.
- scene: the prop drawn above the stickman. Pick the one that best illustrates the sentence, one of: {", ".join(PROPS)}. Avoid using the same prop twice in a row.
- pose: how the stickman moves, one of: {", ".join(POSES)}. Use "point" when referring to the prop, "think" for questions, "shrug" for uncertainty, "excited" for good news, "sad" for pain, "stop" for warnings, "talk" otherwise.
- emotion: the stickman's face, one of: {", ".join(EMOTIONS)}.
- label: 1-3 word on-screen keyword for the scene in plain English (e.g. "Attachment", "The gap"), or an empty string. No emoji.
- caption: short English caption, hook first. hashtags: 6-10 English hashtags. pinned_question: one thoughtful question that invites comments. Never invent statistics, studies or quotes."""

_PUNCT = re.compile(r"[\s\.,!\?…:;\"'“”‘’\-—–()]+")


def clean(text: str) -> str:
    text = re.sub(r"\(\s*(CTA|cta)\s*\)", "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip(s: str) -> str:
    return _PUNCT.sub("", s).lower()


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _spoken(narration: str, spoken) -> str:
    spoken = clean(str(spoken or ""))
    return spoken if spoken and _strip(spoken) == _strip(narration) else narration


def _pick(value, allowed, default):
    value = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return value if value in allowed else default


def _label(value) -> str:
    text = re.sub(r"[^\w\s'!?.-]", "", str(value or "")).strip()
    return " ".join(text.split()[:3])[:28]


def _normalize(data: dict, source: str) -> dict:
    shots = []
    for s in data.get("shots", []):
        narration = clean(str(s.get("narration", "")))
        if not narration:
            continue
        delivery = _pick(s.get("delivery"), DELIVERIES, "calm")
        idx = len(shots)
        prev = shots[-1]["scene"] if shots else None
        fallback_scene = guess_prop(narration, NEUTRAL[idx % len(NEUTRAL)])
        scene = _pick(s.get("scene"), PROPS, fallback_scene)
        if scene == prev and len(PROPS) > 1:  # never the same drawing twice in a row
            scene = fallback_scene if fallback_scene != prev else PROPS[(PROPS.index(prev) + 3) % len(PROPS)]
        shots.append({
            "narration": narration,
            "spoken": _spoken(narration, s.get("spoken")),
            "delivery": delivery,
            "scene": scene,
            "pose": _pick(s.get("pose"), POSES, "talk"),
            "emotion": _pick(s.get("emotion"), EMOTIONS, emotion_for(delivery, narration)),
            "label": _label(s.get("label")),
        })
    if not shots:
        raise SystemExit("No shots with narration found in the input.")
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    return {
        "source": source,
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
    for sent in (s.strip() for s in re.split(r"(?<=[.!?…:])\s+", script) if s.strip()):
        if len(sent.split()) <= 14:
            out.append(sent)
            continue
        buf = ""
        for part in re.split(r"(?<=[,;])\s+", sent):
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
    if len(merged) > 10:
        size = -(-len(merged) // 10)
        merged = [" ".join(merged[i:i + size]) for i in range(0, len(merged), size)]
    return merged or [script]


_FALLBACK_POSES = ("talk", "point", "talk", "shrug", "think", "talk", "point", "hips")


def _fallback(script: str) -> dict:
    parts = _clauses(script)
    shots = []
    for i, p in enumerate(parts):
        delivery = "hook" if i == 0 else "warm" if i == len(parts) - 1 else ("tense" if i % 3 == 1 else "calm")
        shots.append({"narration": p, "delivery": delivery,
                      "scene": guess_prop(p, NEUTRAL[i % len(NEUTRAL)]),
                      "pose": "point" if i == 0 else _FALLBACK_POSES[i % len(_FALLBACK_POSES)],
                      "emotion": emotion_for(delivery, p)})
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
    print("::warning::No AI planner reachable - picking props from keywords. Paste a JSON shot list for full control.")
    return _fallback(script)


def hook_line(shots: list) -> str:
    first = re.split(r"(?<=[.!?…])\s+", shots[0]["narration"])[0]
    return first[:150].strip()
