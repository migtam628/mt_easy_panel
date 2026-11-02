#!/usr/bin/env bash
# Prepare a tested upgrade for an *existing* MT Panel installation.
# Never stop/restart services, switch code, or modify the installed data/config.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$(pwd -P)"

help() {
  cat <<'HELP'
Usage:
  bash scripts/upgrade-vps.sh --check   # Read-only compatibility checks
  bash scripts/upgrade-vps.sh --stage   # Build/test separate release directory

This script is NOT the first-install script.
Staging creates a separate directory under /opt/mt-panel-stage.*.
Existing stages are preserved (up to five total candidates).
It cannot activate an upgrade, restart services or alter credentials/database.
HELP
}
check() {
  [[ -d /opt/mt-panel && -f /opt/mt-panel/requirements.txt ]] ||
    { echo "FAIL: MT Panel is not installed at /opt/mt-panel" >&2; return 1; }
  [[ -f /etc/mt-panel/mt-panel.env && -d /var/lib/mt-panel ]] ||
    { echo "FAIL: MT Panel private configuration/data are missing" >&2; return 1; }
  for command in git python3 tar systemctl; do
    command -v "$command" >/dev/null ||
      { echo "FAIL: Missing command: $command" >&2; return 1; }
  done
  if ! git -C "$SRC" rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "FAIL: Source is not a Git checkout" >&2; return 1
  fi
  # Reject changes to tracked source so the package exactly matches HEAD.
  if ! git -C "$SRC" diff --quiet HEAD --; then
    echo "FAIL: Tracked working tree has edits. Commit/review before staging." >&2
    return 1
  fi
  if ! python3 -m ensurepip --version >/dev/null 2>&1; then
    echo "FAIL: Python venv/ensurepip support missing" >&2; return 1
  fi
  for unit in mt-panel.service mt-panel-agent.service; do
    if [[ "$(systemctl show -p FragmentPath --value "$unit" 2>/dev/null)" != "/etc/systemd/system/$unit" ]]; then
      echo "FAIL: $unit not installed as expected" >&2
      return 1
    fi
  done
  echo "PASS: Source revision $(git -C "$SRC" rev-parse --short HEAD) can be staged separately"
  echo "Existing /opt/mt-panel, /etc/mt-panel and /var/lib/mt-panel will not change"
}
case "${1:---help}" in
  --help|-h) help; exit 0 ;;
  --check) check; exit 0 ;;
  --stage) ;;
  *) help >&2; exit 2 ;;
esac

[[ "$EUID" -eq 0 ]] || { echo "FAIL: --stage requires root" >&2; exit 1; }
check
# Multiple independently tested candidates may coexist. Never overwrite or
# delete an older stage, particularly when it is pending promotion.
# Keep a conservative cap to protect limited VPS disk space.
existing_stages="$(find /opt -mindepth 1 -maxdepth 1 -type d -name 'mt-panel-stage.*' -print | wc -l)"
if [[ "$existing_stages" -ge 5 ]]; then
  echo "FAIL: Five or more staged MT Panel candidates exist under /opt." >&2
  echo "Review existing stages and disk capacity before creating another." >&2
  exit 1
fi
echo "INFO: Preserving $existing_stages existing stage(s); preparing a new candidate."

# git archive ignores all untracked and ignored files (.bashrc, .env, state).
stage="$(mktemp -d /opt/mt-panel-stage.XXXXXXXX)"
cleanup_on_error() {
  code="$?"
  if [[ "$code" -ne 0 ]]; then
    echo "FAIL: Staging failed; deleting only new staging directory" >&2
    rm -rf -- "$stage"
  fi
}
trap cleanup_on_error EXIT
git -C "$SRC" archive --format=tar HEAD | tar -C "$stage" -xf -
python3 -m venv "$stage/.venv"
"$stage/.venv/bin/python" -m pip install -r "$stage/requirements-dev.txt"
(
  cd "$stage"
  .venv/bin/python -m pytest -q
  .venv/bin/python -m compileall -q agent panel
)
if command -v node >/dev/null 2>&1; then
  node --check "$stage/web/app.js"
fi
git -C "$SRC" rev-parse HEAD > "$stage/.staged-commit"
chown -R root:root "$stage"
chmod -R go-w "$stage"
chmod 0755 "$stage"
trap - EXIT
revision="$(cat "$stage/.staged-commit")"
echo "PASS: Upgrade candidate staged and tested: $stage"
echo "STAGE_PATH=$stage"
echo "STAGE_REVISION=$revision"
echo "STAGED ONLY: The running MT Panel code, systemd units, database and credentials were NOT modified."
echo "NEXT - read-only promotion preflight:"
printf '  python3 scripts/promote-vps.py --check --stage %q --expect-commit %q\n' "$stage" "$revision"
echo "AFTER preflight passes - explicitly activate the same tested stage:"
printf '  python3 scripts/promote-vps.py --activate --stage %q --expect-commit %q --confirm ACTIVATE_MT_PANEL\n' "$stage" "$revision"
echo "ONLY AFTER activation, run scripts/verify-live-vps.py --check with the new expected version."
