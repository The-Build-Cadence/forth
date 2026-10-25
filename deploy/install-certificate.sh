#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lineage="${RENEWED_LINEAGE:-${XDG_STATE_HOME:-$HOME/.local/state}/forth/letsencrypt/config/live/forth.mahfouz.ca}"
umask 077
mkdir -p "$project_dir/.secrets/tls"
# The host parent stays private; only the TLS subdirectory is mounted in nginx.
chmod 700 "$project_dir/.secrets"
chmod 755 "$project_dir/.secrets/tls"
install -m 444 "$lineage/fullchain.pem" "$project_dir/.secrets/tls/fullchain.pem"
install -m 444 "$lineage/privkey.pem" "$project_dir/.secrets/tls/privkey.pem"
cd "$project_dir"
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
