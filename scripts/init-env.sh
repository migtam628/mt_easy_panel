#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -e .env ]; then echo '.env already exists; refusing to overwrite.' >&2; exit 1; fi
umask 077
TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(48))')"
sed "s/REPLACE_WITH_64_PLUS_RANDOM_HEX_CHARACTERS/$TOKEN/" .env.example > .env
chmod 600 .env
mkdir -p state
chmod 700 state
echo 'Created .env with a random agent token and restrictive file permissions.'
echo 'Review PANEL_PUBLIC_ORIGIN and PANEL_COOKIE_SECURE before exposing through HTTPS.'
