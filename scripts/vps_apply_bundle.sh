#!/bin/bash
# Applied on VPS by sync_to_vps.ps1
set -euo pipefail
REPO="${1:-/root/agent-arena}"
BUNDLE="${2:-/tmp/agent-arena-from-local.bundle}"
PUSH_ORIGIN="${3:-0}"
REMOTE_CMD="${4:-}"

cd "$REPO"

dirty="$(git status --porcelain | grep -v '^??' || true)"
if [ -n "$dirty" ]; then
  echo "VPS has modified tracked files; commit/stash there first:"
  git status -sb | head -40
  exit 1
fi

git fetch origin master 2>/dev/null || true
git pull --ff-only origin master 2>/dev/null || true

git bundle verify "$BUNDLE"
git pull --ff-only "$BUNDLE"
echo "VPS HEAD: $(git rev-parse --short HEAD)"

if [ "$PUSH_ORIGIN" = "1" ]; then
  git push origin master
  echo "Pushed origin/master"
fi

if [ -n "$REMOTE_CMD" ]; then
  echo "=== remote cmd ==="
  bash -lc "$REMOTE_CMD"
fi
