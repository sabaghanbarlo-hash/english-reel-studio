#!/usr/bin/env bash
# Hosts out/reel.mp4 temporarily on GitHub Pages (Instagram needs a public video URL), publishes it, then removes it.
set -euo pipefail
: "${COMPOSIO_API_KEY:?Add the COMPOSIO_API_KEY repository secret (see README)}"
: "${IG_ACCOUNT:?Set the IG_ACCOUNT repository variable (see README)}"

NAME="reel-${GITHUB_RUN_ID}.mp4"
OWNER_L="$(echo "$GITHUB_REPOSITORY_OWNER" | tr '[:upper:]' '[:lower:]')"
URL="https://${OWNER_L}.github.io/${GITHUB_REPOSITORY#*/}/media/${NAME}"

# Verify the Instagram connection BEFORE publishing anything to the repo.
python -m reel.instagram --check

git config user.name "reel-bot"
git config user.email "reel-bot@users.noreply.github.com"
mkdir -p docs/media
cp out/reel.mp4 "docs/media/${NAME}"
git add "docs/media/${NAME}"
git commit -m "media: ${NAME} (temporary)"
git pull --rebase origin main
git push origin HEAD:main

gh api -X POST "repos/${GITHUB_REPOSITORY}/pages/builds" >/dev/null || true

echo "Waiting for ${URL}"
ok=0
for i in $(seq 1 40); do
  res="$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$URL" || true)"
  echo "  [$i] $res"
  if [[ "$res" == 200\ video* ]]; then ok=1; break; fi
  sleep 15
done
[[ "$ok" == 1 ]] || { echo "Pages never served the video. Is Pages enabled (main:/docs)?"; exit 1; }

status=0
python -m reel.instagram "$URL" || status=$?

git rm -q "docs/media/${NAME}"
git commit -m "media: remove ${NAME}"
git pull --rebase origin main
git push origin HEAD:main
exit $status
