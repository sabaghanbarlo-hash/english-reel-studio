"""Orchestrator: script -> plan -> narration -> visuals -> subtitles -> out/reel.mp4 (+ caption files).

Run from the repo root:  python -m reel.run   (inputs come from environment variables, see the workflow)
"""
import hashlib
import os
from pathlib import Path

from . import planner, render, subtitles, tts, visuals


def main() -> None:
    env = os.environ
    voice = env.get("VOICE") or tts.VOICES["female"]
    provider = env.get("VISUALS") or "pollinations"
    work, out = Path("work"), Path("out")
    work.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)

    plan = planner.plan(env["SCRIPT"])
    shots = plan["shots"]
    print(f"Plan source: {plan['source']} | {len(shots)} shots")
    seed = int(hashlib.sha256("".join(s["narration"] for s in shots).encode()).hexdigest()[:6], 16)

    wavs, shot_durs, audio_durs = [], [], []
    for i, s in enumerate(shots):
        mp3, wav = work / f"seg{i}.mp3", work / f"seg{i}.wav"
        tts.synth(s["narration"], voice, mp3)
        ad = render.duration(mp3)
        pad = 0.45 if i < len(shots) - 1 else 0.8
        render.pad_audio(mp3, wav, pad)
        wavs.append(wav)
        audio_durs.append(ad)
        shot_durs.append(ad + pad)
    total = sum(shot_durs)
    if total > 90:
        raise SystemExit(f"Reel would be {total:.0f}s - Instagram Reels max is 90s. Shorten the script.")
    narration = work / "narration.wav"
    render.concat_audio(wavs, narration)

    clips = []
    for i, s in enumerate(shots):
        vis = visuals.get_visual(provider, s, i, work, plan, seed)
        if vis is None:
            print(f"::warning::No visual for shot {i + 1}; using a dark placeholder.")
        clip = work / f"clip{i}.mp4"
        extra = render.XFADE if i < len(shots) - 1 else 0.0
        render.make_clip(vis, shot_durs[i] + extra, i, clip)
        clips.append(clip)
    joined = work / "joined.mp4"
    render.join_clips(clips, shot_durs, joined)

    starts, t = [], 0.0
    for d in shot_durs:
        starts.append(t)
        t += d
    ass = work / "subs.ass"
    ass.write_text(subtitles.build(shots, starts, audio_durs), encoding="utf-8")

    music = next(iter(sorted(Path("assets/music").glob("*.mp3"))), None)
    render.final_mix(joined, narration, ass, "fonts", music, total, out / "reel.mp4")

    caption = env.get("CAPTION", "").strip() or plan["caption"]
    tags = env.get("HASHTAGS", "").split() or plan["hashtags"]
    tags = [t if t.startswith("#") else "#" + t for t in tags]
    (out / "caption.txt").write_text((caption + "\n\n" + " ".join(tags)).strip(), encoding="utf-8")
    (out / "comment.txt").write_text(plan["pinned_question"], encoding="utf-8")

    summary = [
        "## Reel rendered",
        f"- Length: **{total:.1f}s** ({'inside' if 25 <= total <= 40 else 'OUTSIDE'} the 25-40s target)",
        f"- Shots: {len(shots)} | planner: `{plan['source']}` | visuals: `{provider}` | voice: `{voice}`",
        "- Download the MP4 from this run's **Artifacts**.",
    ]
    if plan["source"] == "fallback":
        summary.append("- Warning: generic prompts were used (AI planner unavailable).")
    if env.get("GITHUB_STEP_SUMMARY"):
        Path(env["GITHUB_STEP_SUMMARY"]).write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
