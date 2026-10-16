#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
certbot_dir="${XDG_DATA_HOME:-$HOME/.local/share}/forth-certbot"
cert_state="${XDG_STATE_HOME:-$HOME/.local/state}/forth/letsencrypt"
exec "$certbot_dir/bin/certbot" renew --quiet \
  --config-dir "$cert_state/config" \
  --work-dir "$cert_state/work" \
  --logs-dir "$cert_state/logs" \
  --deploy-hook "$project_dir/deploy/install-certificate.sh"
