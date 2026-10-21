# English Reel Studio

Paste an **English** script → a **stickman explains it**: narrated, word-highlighted-subtitled **9:16 reel** (25–40 s) → optionally posted to Instagram. Free services only; everything runs on GitHub Actions.

**Web UI:** https://sabaghanbarlo-hash.github.io/english-reel-studio/

## How it works

1. The UI triggers the `Make reel` workflow with your script.
2. **Planner** (GitHub Models, free with the Actions token) splits the narration into 6–10 scenes and, for each, picks a **prop** (brain, clock, phone, heart, ...), a **pose** (point, shrug, think, ...), a **face** (happy, worried, ...) and a 1–3 word on-screen **label**. It also drafts caption, hashtags and a discussion question. It must keep your text word-for-word; if it changes anything, the plan is discarded and a keyword-based fallback is used.
3. **Voice:** Microsoft Edge English neural voices via `edge-tts` (no key). Word timings from the voice drive everything below.
4. **Stickman renderer** (`reel/stickman.py`, Pillow, no extra services): one stickman on screen the whole reel. His mouth opens only while a word is spoken, his arms follow the pose, he blinks, hops on every scene change, and the prop pops in above his head.
5. **FFmpeg** mixes the video with the narration, a soft generated pad (or your own music) and **karaoke-style subtitles** (Poppins ExtraBold, the spoken word in yellow), placed clear of Instagram's bottom UI and right-side icons.
6. The MP4 is uploaded as a run artifact. If you chose *Render and post*, it is hosted briefly on GitHub Pages, published to Instagram **through Composio** (no Meta developer account needed), then deleted from the repo.

Props: brain, heart, broken_heart, clock, phone, bulb, question, alert, chart_up, chart_down, people, house, magnifier, lock, battery, scale, mask, target, book, eyes. Poses: idle, talk, point, shrug, think, excited, sad, stop, hips. Faces: neutral, happy, sad, surprised, angry, worried, thinking.

## One-time setup

1. **Pages** is already set to `main` / `/docs`.
2. **Token for the UI:** GitHub → Settings → Developer settings → Fine-grained tokens → this repo only → *Actions: Read and write*. Paste it into the UI's Connect box.
3. **Instagram posting (optional until you want it):**
   - In Composio, connect the Instagram account that should receive the reels (Business or Creator). Give the connection a recognisable alias.
   - Repo → Settings → Secrets and variables → Actions → **Secrets**: add `COMPOSIO_API_KEY` (your Composio consumer key).
   - Same page → **Variables**: add `IG_ACCOUNT` (the connection's alias or id). It has no default on purpose, so nothing is posted to the wrong account.
   - Optional variable `IG_EXPECT_USERNAME`: posting aborts unless the connected account has this username.
   - Run the **Check Instagram connection** workflow from the Actions tab; it prints the connected `@username` and posts nothing.
4. **Music (optional):** put one licensed `.mp3` in `assets/music/`.

Start with **Render only**, check the MP4, then switch to posting.

## Manual shot list (full control)

Paste JSON instead of plain text. `scene`, `pose`, `emotion` and `label` are all optional (unknown values fall back to a sensible pick):

```json
{
  "shots": [
    {"narration": "Your brain hates unfinished things.", "scene": "brain", "pose": "point", "emotion": "surprised", "label": "Open loops"},
    {"narration": "That is why you replay arguments at 2 a.m.", "scene": "clock", "pose": "shrug", "emotion": "worried"}
  ],
  "caption": "...", "hashtags": ["#psychology"], "pinned_question": "..."
}
```

## Honest limits

- This is a **2D stickman explainer**, not AI video. It is fully free and deterministic, but every scene is one of the built-in props. New props are a ~15-line function in `reel/stickman.py` (add the name to `reel/vocab.py` too).
- The Edge voices are good, not human. Try a few (Andrew, Brian, Ryan are the calmest) and keep the one that suits the channel.
- The discussion question is not posted automatically; the run summary shows it so you can add and pin it in the app.
- Fact-check the script yourself before posting. The tool never invents claims, but it does not verify yours. Psychology content is easy to overstate; name the effect or study accurately.
- The default posting slots (12:30 and 20:00 New York time) are a reasoned starting guess for an English-speaking audience, **not measured data**. Edit `queue/schedule.json` after you have a few weeks of Instagram Insights.

## Layout

```
.github/workflows/make-reel.yml          workflow_dispatch pipeline
.github/workflows/check-instagram.yml    verifies the Composio/Instagram link, posts nothing
.github/workflows/test-render.yml        offline stickman render with a silent mock voice (no keys)
reel/            planner, vocab, tts, stickman (renderer), subtitles, render (ffmpeg mix), instagram (Composio), run
scripts/post.sh  temporary Pages hosting + publish + cleanup
scripts/test_render.py  local smoke test: python scripts/test_render.py
docs/index.html  web UI (GitHub Pages)
```

## Scheduling (queue)

Choose **Queue for the best time** in the UI (or `after_render = queue_for_best_time`). The finished reel waits in the repo and the **Publish queue** workflow (runs every 15 minutes) posts it at its slot.

- Slots live in `queue/schedule.json`: a timezone and a list of `HH:MM` times, one reel per slot. The default is **12:30 and 20:00 America/New_York**. These are reasoned starting guesses for English-speaking viewers (lunch break and evening scroll), **not measured data**. After a few weeks, compare against Instagram Insights (most active times / reel reach) and edit the file.
- A new reel takes the earliest free slot at least 30 minutes away. The run summary shows the exact time.
- GitHub's cron is not exact; posts can be several minutes late.
- A reel is marked `publishing` and pushed *before* Instagram is called, so a crash never double-posts. Failures are **not** retried automatically (the run turns red and GitHub emails you). Check Instagram, then run **Publish queue** manually with *requeue_failed* ticked.
- While waiting, the video sits in `docs/queue/` of this public repo, so anyone who finds the URL could see it before it is posted. It is deleted after posting, but git history keeps the file.
- A reel can't be queued with an empty caption. If the AI planner fails and you typed none, the first sentence of your script is used.
