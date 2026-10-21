"""Orchestrator: script -> plan -> narration (with word timings) -> stickman video -> word-by-word subtitles -> out/reel.mp4.

Run from the repo root:  python -m reel.run   (inputs come from environment variables, see the workflow)
"""
import os
from pathlib import Path

from . import narration, planner, render, stickman, subtitles, tts


def main() -> None:
    env = os.environ
    voice = env.get("VOICE") or tts.VOICES["male"]
    work, out = Path("work"), Path("out")
    work.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)

    plan = planner.plan(env["SCRIPT"])
    shots = plan["shots"]
    print(f"Plan source: {plan['source']} | {len(shots)} scenes")
    for i, s in enumerate(shots, 1):
        print(f"  {i}. [{s['scene']} / {s['pose']} / {s['emotion']}] {s['narration']}")

    nar = narration.build(plan, voice, work)
    total = nar["total"]
    if total > 90:
        raise SystemExit(f"Reel would be {total:.0f}s - Instagram Reels max is 90s. Shorten the script.")

    silent = work / "stickman.mp4"
    stickman.render_video(plan, nar, silent)

    ass = work / "subs.ass"
    ass.write_text(subtitles.build(nar["words"]), encoding="utf-8")

    music = next(iter(sorted(Path("assets/music").glob("*.mp3"))), None)
    render.final_mix(silent, nar["wav"], ass, "fonts", music, total, out / "reel.mp4", pad=env.get("PAD", "1") != "0")

    caption = env.get("CAPTION", "").strip() or plan["caption"] or planner.hook_line(shots)
    tags = env.get("HASHTAGS", "").split() or plan["hashtags"]
    tags = [t if t.startswith("#") else "#" + t for t in tags]
    (out / "caption.txt").write_text((caption + "\n\n" + " ".join(tags)).strip(), encoding="utf-8")
    (out / "comment.txt").write_text(plan["pinned_question"], encoding="utf-8")

    summary = [
        "## Reel rendered",
        f"- Length: **{total:.1f}s** ({'inside' if 25 <= total <= 40 else 'OUTSIDE'} the 25-40s target)",
        f"- Scenes: {len(shots)} | planner: `{plan['source']}` | style: stickman explainer | voice: `{voice}`",
        f"- File size: **{(out / 'reel.mp4').stat().st_size / 1e6:.1f} MB**",
        "- Download the MP4 from this run's **Artifacts**.",
    ]
    if plan["source"] == "fallback":
        summary.append("- Warning: props were picked from keywords (AI planner unavailable).")
    if env.get("GITHUB_STEP_SUMMARY"):
        Path(env["GITHUB_STEP_SUMMARY"]).write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
