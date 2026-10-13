"""Publish out/reel.mp4 (already hosted at a public URL) as an Instagram Reel via the Graph API.

Usage: python -m reel.instagram <public_video_url>
Env:   IG_USER_ID, IG_ACCESS_TOKEN, optional IG_GRAPH_HOST (default graph.facebook.com;
       use graph.instagram.com if your token comes from 'Instagram API with Instagram Login')
"""
import os
import sys
import time
from pathlib import Path

import requests

VERSION = "v21.0"


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    if not r.ok or "error" in data:
        raise SystemExit(f"Instagram API error ({r.status_code}): {data}")
    return data


def main() -> None:
    video_url = sys.argv[1]
    uid, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    base = f"https://{os.environ.get('IG_GRAPH_HOST', 'graph.facebook.com')}/{VERSION}"
    caption = Path("out/caption.txt").read_text(encoding="utf-8")

    container = _check(requests.post(f"{base}/{uid}/media", data={
        "media_type": "REELS", "video_url": video_url, "caption": caption,
        "share_to_feed": "true", "access_token": token}, timeout=60))["id"]
    print(f"Container created: {container}")

    for _ in range(60):
        st = _check(requests.get(f"{base}/{container}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        code = st.get("status_code")
        print(f"Processing status: {code}")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise SystemExit(f"Instagram could not process the video: {st}")
        time.sleep(10)
    else:
        raise SystemExit("Timed out waiting for Instagram to process the video.")

    media_id = _check(requests.post(f"{base}/{uid}/media_publish", data={
        "creation_id": container, "access_token": token}, timeout=60))["id"]
    link = _check(requests.get(f"{base}/{media_id}", params={
        "fields": "permalink", "access_token": token}, timeout=30)).get("permalink", media_id)
    print(f"Published: {link}")

    question = Path("out/comment.txt").read_text(encoding="utf-8").strip()
    if question:
        try:
            _check(requests.post(f"{base}/{media_id}/comments", data={
                "message": question, "access_token": token}, timeout=30))
            print("Posted the discussion question as a comment (pin it manually in the app).")
        except SystemExit as exc:
            print(f"::warning::Could not post the comment: {exc}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"\n## Posted to Instagram\n{link}\n")


if __name__ == "__main__":
    main()
