"""Publishing queue: finished reels wait in the repo until their slot, then a scheduled workflow posts them.

  python -m reel.queue add       add out/reel.mp4 (+ caption) at the next free slot
  python -m reel.queue due       report whether anything is due (sets GITHUB_OUTPUT due=true|false)
  python -m reel.queue publish   publish the oldest due item
  python -m reel.queue requeue   move failed items back into the queue
  python -m reel.queue list      show the queue
  python -m reel.queue preview   publish out/reel.mp4 to the site's Latest renders (keeps the newest 6)

Slots come from queue/schedule.json (timezone + list of HH:MM times). Each slot holds one reel.
Safety: an item is marked "publishing" and pushed BEFORE Instagram is called, so a crash can never
cause a double post. Failures are not retried automatically; use `requeue` after checking Instagram.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

QUEUE, MEDIA = Path("queue"), Path("docs/queue")
POSTED = QUEUE / "posted"
DEFAULT_CFG = {"timezone": "Asia/Tehran", "slots": ["13:30", "21:30"], "min_lead_minutes": 30}


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def cfg():
    p = QUEUE / "schedule.json"
    return {**DEFAULT_CFG, **json.loads(p.read_text(encoding="utf-8"))} if p.exists() else dict(DEFAULT_CFG)


def items():
    out = []
    for p in sorted(QUEUE.glob("*.json")):
        if p.name != "schedule.json":
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def save(item, path=None):
    path = path or QUEUE / f"{item['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")


def note(text):
    print(text, flush=True)
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def sh(*args, check=True):
    print("$", " ".join(args), flush=True)
    return subprocess.run(list(args), check=check)


def push(msg):
    sh("git", "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    sh("git", "commit", "-m", msg)
    for attempt in range(4):
        sh("git", "pull", "--rebase", "origin", "main")
        if sh("git", "push", "origin", "HEAD:main", check=False).returncode == 0:
            return
        time.sleep(3 * (attempt + 1))
    raise SystemExit("Could not push to main.")


def next_slot(taken):
    c = cfg()
    tz = ZoneInfo(c["timezone"])
    earliest = now() + timedelta(minutes=c["min_lead_minutes"])
    day = earliest.astimezone(tz).date()
    for offset in range(120):
        d = day + timedelta(days=offset)
        for hhmm in sorted(c["slots"]):
            h, m = (int(x) for x in hhmm.split(":"))
            cand = datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc)
            if cand >= earliest and iso(cand) not in taken:
                return cand
    raise SystemExit("No free slot in the next 120 days.")


def request_pages_build():
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return
    try:
        subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/pages/builds"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def wait_for(url, tries=12, delay=15):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200 and r.headers.get("Content-Type", "").startswith("video"):
                    return True
                print(f"  [{i + 1}] {r.status} {r.headers.get('Content-Type')}")
        except Exception as exc:
            print(f"  [{i + 1}] {exc}")
        time.sleep(delay)
    return False


def cmd_add():
    video = Path("out/reel.mp4")
    if not video.exists():
        sys.exit("out/reel.mp4 not found.")
    caption = Path("out/caption.txt").read_text(encoding="utf-8").strip()
    if not caption:
        sys.exit("Refusing to queue a reel with an empty caption.")
    cpath = Path("out/comment.txt")
    question = cpath.read_text(encoding="utf-8").strip() if cpath.exists() else ""
    rid = f"reel-{os.environ.get('RUN_ID') or int(time.time())}"
    QUEUE.mkdir(exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    taken = {i["scheduled_at"] for i in items() if i["status"] in ("queued", "publishing")}
    slot = next_slot(taken)
    shutil.copy(video, MEDIA / f"{rid}.mp4")
    save({"id": rid, "status": "queued", "scheduled_at": iso(slot), "video": f"docs/queue/{rid}.mp4",
          "caption": caption, "question": question, "created_at": iso(now()), "error": None})
    push(f"queue: add {rid} for {iso(slot)}")
    request_pages_build()
    local = slot.astimezone(ZoneInfo(cfg()["timezone"]))
    note(f"## Queued\n- Scheduled for **{local:%a %d %b %Y, %H:%M}** ({cfg()['timezone']}) = `{iso(slot)}`\n"
         f"- Waiting in the queue: {sum(1 for i in items() if i['status'] == 'queued')}")


def cmd_due():
    t = now()
    all_items = items()
    for i in all_items:
        if i["status"] in ("publishing", "failed"):
            print(f"::warning::{i['id']} is '{i['status']}' ({i.get('error') or 'check Instagram before retrying'}).")
    due = [i for i in all_items if i["status"] == "queued" and parse(i["scheduled_at"]) <= t]
    waiting = sum(1 for i in all_items if i["status"] == "queued")
    print(f"{len(due)} due, {waiting} waiting.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"due={'true' if due else 'false'}\n")


def cmd_publish():
    from . import instagram
    t = now()
    due = sorted((i for i in items() if i["status"] == "queued" and parse(i["scheduled_at"]) <= t),
                 key=lambda i: i["scheduled_at"])
    if not due:
        print("Nothing due.")
        return
    item = due[0]
    item.update(status="publishing", started_at=iso(t), error=None)
    save(item)
    push(f"queue: publishing {item['id']}")
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, name = repo.split("/")
    url = f"https://{owner.lower()}.github.io/{name}/queue/{item['id']}.mp4"
    if not wait_for(url):
        item.update(status="queued", error="video not served by Pages yet")
        save(item)
        push(f"queue: {item['id']} back in queue (Pages not ready)")
        sys.exit("Pages is not serving the video yet; will retry on the next run.")
    try:
        username, media_id = instagram.publish(url, item["caption"])
    except SystemExit as exc:
        item.update(status="failed", error=str(exc.code)[:500])
        save(item)
        push(f"queue: {item['id']} failed")
        sys.exit(f"Publishing failed: {exc.code}")
    item.update(status="posted", posted_at=iso(now()), media_id=media_id, account=username)
    save(item, POSTED / f"{item['id']}.json")
    (QUEUE / f"{item['id']}.json").unlink(missing_ok=True)
    (MEDIA / f"{item['id']}.mp4").unlink(missing_ok=True)
    push(f"queue: posted {item['id']}")
    note(f"## Posted to Instagram (@{username})\nMedia id: `{media_id}`")
    if item.get("question"):
        note(f"\nDiscussion question to add and pin as the first comment:\n\n> {item['question']}")


def cmd_requeue():
    n = 0
    for i in items():
        if i["status"] == "failed":
            i.update(status="queued", scheduled_at=iso(now()), error=None)
            save(i)
            n += 1
    print(f"Re-queued {n} item(s); they publish on the next run.")
    push("queue: requeue failed items")


PREVIEWS = Path("docs/previews")
KEEP_PREVIEWS = 6


def cmd_preview():
    video = Path("out/reel.mp4")
    if not video.exists():
        sys.exit("out/reel.mp4 not found.")
    cap, cq = Path("out/caption.txt"), Path("out/comment.txt")
    rid = f"reel-{os.environ.get('RUN_ID') or int(time.time())}"
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    shutil.copy(video, PREVIEWS / f"{rid}.mp4")
    meta = {"id": rid, "created_at": iso(now()),
            "caption": cap.read_text(encoding="utf-8").strip() if cap.exists() else "",
            "question": cq.read_text(encoding="utf-8").strip() if cq.exists() else ""}
    (PREVIEWS / f"{rid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def num(stem):
        tail = stem.split("-")[-1]
        return int(tail) if tail.isdigit() else 0

    stems = sorted({p.stem for p in PREVIEWS.glob("reel-*.json")}, key=num, reverse=True)
    for stem in stems[KEEP_PREVIEWS:]:
        (PREVIEWS / f"{stem}.mp4").unlink(missing_ok=True)
        (PREVIEWS / f"{stem}.json").unlink(missing_ok=True)
    push(f"preview: {rid}")
    request_pages_build()
    note("## Preview ready\nOpen the site and look under **Latest renders** (it appears about a minute after this run ends).")


def cmd_list():
    for i in items():
        print(i["scheduled_at"], i["status"], i["id"], (i.get("error") or ""))


if __name__ == "__main__":
    cmds = {"add": cmd_add, "due": cmd_due, "publish": cmd_publish, "requeue": cmd_requeue, "list": cmd_list,
            "preview": cmd_preview}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
