"""Publish out/reel.mp4 (already hosted at a public URL) as an Instagram Reel through Composio's MCP server.

No Meta developer account is needed: Composio holds the Instagram connection you authorised there.

Usage:  python -m reel.instagram <public_video_url>
        python -m reel.instagram --check        (verify key + connection, post nothing)
Env:    COMPOSIO_API_KEY            your Composio consumer key
        IG_ACCOUNT                  alias or id of the Composio Instagram connection to use (required)
        IG_EXPECT_USERNAME          optional safety check: abort unless the connected account has this username
"""
import json
import os
import sys
from pathlib import Path

import requests

MCP_URL = "https://connect.composio.dev/mcp"
KEY = os.environ.get("COMPOSIO_API_KEY", "").strip()
ACCOUNT = os.environ.get("IG_ACCOUNT", "").strip()
_state = {"session": None, "n": 0}


def _post(payload):
    headers = {
        "x-consumer-api-key": KEY,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _state["session"]:
        headers["Mcp-Session-Id"] = _state["session"]
    r = requests.post(MCP_URL, data=json.dumps(payload), headers=headers, timeout=400)
    if not r.ok:
        sys.exit(f"Composio MCP returned HTTP {r.status_code}: {r.text[:500]}")
    _state["session"] = r.headers.get("Mcp-Session-Id") or _state["session"]
    raw = r.text.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    for line in reversed([ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _rpc(method, params=None, notify=False):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if not notify:
        _state["n"] += 1
        msg["id"] = _state["n"]
    return _post(msg)


def _start():
    r = _rpc("initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "persian-reel-studio", "version": "1.0"},
    })
    if not r or "error" in r:
        sys.exit(f"Composio MCP initialize failed: {str(r)[:400]}")
    _rpc("notifications/initialized", notify=True)


def tool(slug, args):
    r = _rpc("tools/call", {
        "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
        "arguments": {
            "tools": [{"tool_slug": slug, "account": ACCOUNT, "arguments": args}],
            "sync_response_to_workbench": False,
        },
    })
    if not r or "error" in r:
        sys.exit(f"{slug} failed: {str(r)[:500]}")
    res = r.get("result", {})
    text = "".join(c.get("text", "") for c in res.get("content", []) if isinstance(c, dict))
    try:
        top = json.loads(text)
    except ValueError:
        sys.exit(f"{slug}: unreadable answer from Composio: {text[:500]}")
    items = (top.get("data") or {}).get("results") or []
    if res.get("isError") or not top.get("successful", True) or not items:
        err = (items[0].get("error") if items else None) or top.get("error") or top
        sys.exit(f"{slug} failed: {str(err)[:600]}")
    resp = items[0].get("response", {})
    if not resp.get("successful", True):
        sys.exit(f"{slug} failed: {str(resp.get('error') or resp)[:600]}")
    return resp


def find(obj, key):
    if isinstance(obj, dict):
        if isinstance(obj.get(key), (str, int)):
            return str(obj[key])
        for v in obj.values():
            got = find(v, key)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find(v, key)
            if got:
                return got
    return None


def _connect():
    if not KEY:
        sys.exit("Add the COMPOSIO_API_KEY repository secret (see README).")
    if not ACCOUNT:
        sys.exit("Set the IG_ACCOUNT repository variable to the alias or id of the Composio Instagram connection "
                 "for the Persian account. It is required so nothing is posted to the wrong account.")
    _start()
    info = tool("INSTAGRAM_GET_USER_INFO", {"ig_user_id": "me", "fields": "id,username,account_type"})
    username = find(info.get("data"), "username") or "(unknown)"
    print(f"Connected Instagram account: @{username}", flush=True)
    expected = os.environ.get("IG_EXPECT_USERNAME", "").strip().lstrip("@")
    if expected and expected.lower() != username.lower():
        sys.exit(f"Refusing to post: connected account is @{username}, expected @{expected}.")
    return username


def publish(video_url, caption):
    """Post one Reel. Returns (username, media_id). Exits with a message on any failure."""
    username = _connect()
    c = tool("INSTAGRAM_POST_IG_USER_MEDIA", {
        "ig_user_id": "me", "video_url": video_url, "media_type": "REELS",
        "caption": caption, "share_to_feed": True,
    })
    container = find(c.get("data"), "id")
    if not container:
        sys.exit(f"No container id in Composio's answer: {str(c)[:400]}")
    print(f"Container: {container}", flush=True)
    p = tool("INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH", {
        "ig_user_id": "me", "creation_id": container, "max_wait_seconds": 300,
    })
    media_id = find(p.get("data"), "id")
    if not media_id:
        sys.exit(f"Instagram did not confirm a published id: {str(p)[:400]}")
    print(f"Published media id: {media_id}", flush=True)
    return username, media_id


def main():
    if "--check" in sys.argv:
        _connect()
        print("CHECK OK - nothing was posted.")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    caption = Path("out/caption.txt").read_text(encoding="utf-8")
    username, media_id = publish(args[0], caption)
    cpath = Path("out/comment.txt")
    question = cpath.read_text(encoding="utf-8").strip() if cpath.exists() else ""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"\n## Posted to Instagram (@{username})\nMedia id: `{media_id}`\n")
            if question:
                f.write(f"\nDiscussion question to pin as the first comment:\n\n> {question}\n")


if __name__ == "__main__":
    main()
