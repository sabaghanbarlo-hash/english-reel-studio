# Persian Reel Studio

Paste a Persian script → narrated, subtitled **9:16 reel** (25–40 s) → optionally posted to Instagram. Built for the faceless account «پشتِ رفتار». Free services only; everything runs on GitHub Actions.

**Web UI:** https://sabaghanbarlo-hash.github.io/persian-reel-studio/

## How it works

1. The UI triggers the `Make reel` workflow with your script.
2. **Planner** (GitHub Models, free with the Actions token) splits the narration into 4–7 shots, writes English visual prompts with one fixed character sheet, and drafts caption, hashtags and a discussion question. It must keep your text word-for-word; if it changes anything, the plan is discarded and a plain sentence splitter is used.
3. **Voice:** Microsoft Edge Persian neural voices via `edge-tts` (no key).
4. **Visuals:** `pollinations` (free AI stills with a slow camera move) or `pexels` (free stock video).
5. **FFmpeg** assembles crossfaded shots, narration, optional music and **Persian ASS subtitles** (Vazirmatn, kept above Instagram's bottom UI and clear of the right-side icons).
6. The MP4 is uploaded as a run artifact. If you chose *Render and post*, it is hosted briefly on GitHub Pages, published through the Instagram Graph API, then deleted from the repo.

## One-time setup

1. **Pages** is already set to `main` / `/docs`.
2. **Token for the UI:** GitHub → Settings → Developer settings → Fine-grained tokens → this repo only → *Actions: Read and write*. Paste it into the UI's Connect box.
3. **Instagram posting (optional until you want it):**
   - Instagram account must be **Business or Creator**; with the Facebook-login route it must be linked to a Facebook Page.
   - Create a Meta developer app, get a token with `instagram_content_publish` (and `instagram_basic`, `pages_show_list`), and find your Instagram user ID.
   - Repo → Settings → Secrets and variables → Actions → add secrets `IG_USER_ID` and `IG_ACCESS_TOKEN`.
   - If your token is from *Instagram API with Instagram Login*, add the repository variable `IG_GRAPH_HOST` = `graph.instagram.com`.
   - Long-lived tokens expire after ~60 days; refresh them.
4. **Pexels (optional):** free key from pexels.com/api → secret `PEXELS_API_KEY`.
5. **Music (optional):** put one licensed `.mp3` in `assets/music/`.

Start with **Render only**, check the MP4, then switch to posting.

## Manual shot list (full control)

Paste JSON instead of plain text:

```json
{
  "character_sheet": "Iranian woman, late 20s, shoulder-length dark wavy hair, cream knit sweater; man ~30, short dark hair, stubble, dark gray henley; modern apartment, warm lamp light",
  "shots": [
    {"narration": "متن شات اول", "prompt": "close-up, tense expression, slow push-in", "stock_query": "couple argument"}
  ],
  "caption": "...", "hashtags": ["#روانشناسی"], "pinned_question": "..."
}
```

## Honest limits

- GitHub's free runners have no GPU, so this does **not** generate true AI video. "AI stills + camera move" is the free default; real video models (Wan 2.2, LTX-Video) would be a new provider in `reel/visuals.py` on a GPU machine.
- Character consistency across AI stills is approximate (shared character sheet + fixed seed).
- Instagram's API cannot **pin** comments; the discussion question is posted as a comment and you pin it in the app.
- Pollinations is a free public service and can be slow or rate-limited; failed shots become a dark placeholder with a warning in the log.
- Fact-check the script yourself (e.g. Gottman Institute material) before posting. The tool never invents claims, but it does not verify yours.

## Layout

```
.github/workflows/make-reel.yml   workflow_dispatch pipeline
reel/            planner, tts, visuals, subtitles, render, instagram, run
scripts/post.sh  temporary Pages hosting + publish + cleanup
docs/index.html  web UI (GitHub Pages)
```
