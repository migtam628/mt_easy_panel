#!/usr/bin/env bash
# Prepare the MT Panel pilot for Tailscale-only HTTPS.
# Does not start/stop any service or modify existing Tailscale Serve routes.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  bash scripts/tailscale-access.sh --check    # Read-only preflight
  bash scripts/tailscale-access.sh --prepare  # Change MT Panel origin/cookie only

Tailscale Serve HTTPS port 8443 -> http://127.0.0.1:8086.
Never enables Funnel, public TCP listeners, or an SSH tunnel.
Does not configure Serve, stop services or alter any existing Serve port.
HELP
}

case "${1:---help}" in
  -h|--help) usage; exit 0 ;;
  --check|--prepare) MODE="$1" ;;
  *) usage >&2; exit 2 ;;
esac
fail() { echo "FAIL: $*" >&2; exit 1; }
command -v tailscale >/dev/null || fail "Tailscale CLI is not installed"
command -v python3 >/dev/null || fail "Python is not installed"
command -v ss >/dev/null || fail "'ss' is not installed"

# Extract only the DNS name. Never print the rest of the status JSON.
fqdn="$(
  tailscale status --json | python3 -c '
import json, re, sys
try:
    name = json.load(sys.stdin)["Self"]["DNSName"].rstrip(".").lower()
except (KeyError, ValueError, TypeError, AttributeError):
    sys.exit(2)
if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net", name):
    sys.exit(2)
print(name)
'
)" || fail "No valid Tailscale *.ts.net hostname; check tailscale status and MagicDNS"

url="https://${fqdn}:8443"
echo "Private MT Panel URL: $url"

# Conservative conflict check: never overwrite existing port 8443.
# Existing Tailnet 443 routes are intentionally preserved.
serve_status="$(tailscale serve status --json 2>/dev/null || true)"
if printf '%s' "$serve_status" | grep -q '8443'; then
  fail "Tailscale Serve already uses/mentions port 8443. Inspect 'tailscale serve status' first."
fi
funnel_status="$(tailscale funnel status 2>/dev/null || true)"
if printf '%s' "$funnel_status" | grep -q '8443'; then
  fail "Tailscale Funnel already uses/mentions port 8443. Do not override a public route."
fi
if ss -H -lnt | awk '{print $4}' | grep -Eq ':8443$'; then
  fail "TCP port 8443 already has a listener; inspect 'ss -lntp' first."
fi

if [[ "$MODE" == "--check" ]]; then
  echo "PASS: Tailscale access preflight; no changes made."
  echo "After you start MT Panel, enable private Serve manually:"
  echo "  tailscale serve --bg --https=8443 http://127.0.0.1:8086"
  exit 0
fi

[[ "$EUID" -eq 0 ]] || fail "--prepare requires root"
config=/etc/mt-panel/mt-panel.env
[[ -f "$config" ]] || fail "Stage the MT Panel systemd installation first."
if systemctl is-active --quiet mt-panel.service; then
  fail "Stop only mt-panel.service before changing its origin."
fi

# Atomic root-only update; never output or replace the random agent token.
python3 - "$config" "$url" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

target = Path(sys.argv[1])
url = sys.argv[2]
rows = target.read_text(encoding="utf-8").splitlines()
changes = {"PANEL_PUBLIC_ORIGIN": url, "PANEL_COOKIE_SECURE": "true"}
for key in changes:
    if sum(row.startswith(key + "=") for row in rows) != 1:
        raise SystemExit(f"Expected exactly one {key} in the configuration")
revised = []
for row in rows:
    key = row.split("=", 1)[0]
    revised.append(key + "=" + changes[key] if key in changes else row)
fd, name = tempfile.mkstemp(prefix=".mt-panel-env-", dir=target.parent)
try:
    os.fchmod(fd, 0o600)
    os.fchown(fd, 0, 0)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write("\n".join(revised) + "\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(name, target)
except BaseException:
    try:
        os.unlink(name)
    except FileNotFoundError:
        pass
    raise
PY
echo "Prepared MT Panel's private HTTPS origin and Secure cookie:"
echo "  PANEL_PUBLIC_ORIGIN=$url"
echo "  PANEL_COOKIE_SECURE=true"
echo "Start the MT Panel units, then explicitly enable Serve on port 8443."
