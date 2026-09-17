#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo/root: sudo bash scripts/bootstrap_server.sh <deploy-user>" >&2
  exit 1
fi

DEPLOY_USER="${1:-${SUDO_USER:-}}"
if [[ -z "$DEPLOY_USER" || "$DEPLOY_USER" == "root" ]]; then
  echo "Pass the non-root SSH/deploy username as the first argument." >&2
  exit 1
fi

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "Deploy user does not exist: $DEPLOY_USER" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg git

if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker
usermod -aG docker "$DEPLOY_USER"
install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/hai-search

echo "Bootstrap complete."
echo "Cloud/firewall must allow inbound TCP 80/443 (and UDP 443 for HTTP/3)."
echo "Reconnect the SSH session so Docker group membership is refreshed."
