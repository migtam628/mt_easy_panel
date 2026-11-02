#!/usr/bin/env bash
# Keep the *source checkout and tested stage* current. Never deploy automatically.
# This is intentionally NOT a cron, systemd timer, or unattended updater.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$(pwd -P)"

usage() {
  cat <<'HELP'
Usage:
  bash scripts/vps-test-sync.sh --check   # Read-only: source and live release
  bash scripts/vps-test-sync.sh --stage   # Fast-forward Git checkout and safely stage

Neither mode activates a release, modifies /opt/mt-panel, /var/lib/mt-panel,
Tailscale, Caddy, Docker containers, or systemd services.
--stage requires root and prints exact operator-approved promotion commands.
Never use this helper to enable lab Docker write execution on production.
HELP
}

mode="${1:---help}"
case "$mode" in
  --help|-h) usage; exit 0 ;;
  --check|--stage) ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$(git -C "$SRC" symbolic-ref --quiet --short HEAD || true)" != main ]]; then
  echo "FAIL: Use the reviewed main branch only" >&2
  exit 1
fi
if ! git -C "$SRC" diff --quiet HEAD --; then
  echo "FAIL: Tracked checkout changes present; review before upgrading" >&2
  exit 1
fi
if [[ "$mode" == --check ]]; then
  python3 scripts/release-status.py --check
  echo "PASS: Read-only sync status; no Git fetch or deployment performed"
  exit 0
fi

[[ "$EUID" -eq 0 ]] || {
  echo "FAIL: Safe staging requires root on the existing VPS" >&2; exit 1;
}
[[ -f /opt/mt-panel/requirements.txt ]] || {
  echo "FAIL: Installed MT Panel not found; use the first-install runbook" >&2; exit 1;
}

# The only network action is fetching the reviewed repository's main branch.
git -C "$SRC" pull --ff-only origin main
revision="$(git -C "$SRC" rev-parse HEAD)"
echo "GIT_SOURCE_REVISION=$revision"
python3 scripts/release-status.py --check

if [[ -f /opt/mt-panel/.staged-commit ]] &&
   [[ "$(cat /opt/mt-panel/.staged-commit)" == "$revision" ]]; then
  echo "PASS: This exact revision is already installed. No stage created."
  echo "Verify it separately with scripts/verify-live-vps.py --check."
  exit 0
fi

# Never repeat the stage for the same pinned SHA and exhaust the cap.
for candidate in /opt/mt-panel-stage.*; do
  [[ -d "$candidate" && ! -L "$candidate" &&
     -f "$candidate/.staged-commit" &&
     ! -L "$candidate/.staged-commit" ]] || continue
  if [[ "$(cat "$candidate/.staged-commit")" == "$revision" ]]; then
    echo "PASS: Existing stage matches the latest commit: $candidate"
    echo "STAGE_PATH=$candidate"
    echo "STAGE_REVISION=$revision"
    echo "NEXT: read-only preflight"
    printf '  python3 scripts/promote-vps.py --check --stage %q --expect-commit %q\n' "$candidate" "$revision"
    echo "ONLY after PASS, operator-approved activation:"
    printf '  python3 scripts/promote-vps.py --activate --stage %q --expect-commit %q --confirm ACTIVATE_MT_PANEL\n' "$candidate" "$revision"
    echo "No live code, containers, Tailscale, or proxy settings changed."
    exit 0
  fi
done

bash scripts/upgrade-vps.sh --check
bash scripts/upgrade-vps.sh --stage
