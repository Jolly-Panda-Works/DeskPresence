#!/usr/bin/env bash
# Installs (or updates) the DeskPresence relay on a Linux VPS with Docker + Caddy (automatic HTTPS).
#
#   curl -fsSL https://raw.githubusercontent.com/Jolly-Panda-Works/DeskPresence/main/relay/install.sh \
#     | sudo bash -s deskpresence.example.com
#
# Before running: point the domain's DNS A record to this server, and open ports 80 and 443.
set -euo pipefail

DOMAIN="${1:-}"
REPO="${REPO:-https://github.com/Jolly-Panda-Works/DeskPresence.git}"
DIR=/opt/deskpresence

if [ -z "$DOMAIN" ]; then
  echo "Usage: install.sh <domain>   e.g. install.sh deskpresence.example.com" >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "== Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
if ! command -v git >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y git
fi

echo "== Getting the relay"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp && ufw allow 443/tcp
fi

echo "== Starting (Caddy gets the HTTPS certificate automatically)"
cd "$DIR/relay"
echo "DOMAIN=$DOMAIN" > .env
docker compose up -d --build

echo
echo "Done. Check: curl https://$DOMAIN/health"
echo "In DeskPresence on the PC: Settings -> Mobile app -> Relay address: https://$DOMAIN"
