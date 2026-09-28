#!/usr/bin/env bash
# Builds deploy/oracle-setup.sh: the installer with the app files embedded,
# so it works on a fresh VM without cloning this (private) repo.
set -euo pipefail
cd "$(dirname "$0")/.."
out=deploy/oracle-setup.sh
{
  sed -n '1,/^#@@FILES@@$/p' deploy/setup.template.sh | sed '$d'
  for f in server.py requirements.txt Dockerfile docker-compose.yml Caddyfile; do
    printf "cat > %s <<'__EOF_%s__'\n" "$f" "${f//[.-]/_}"
    cat "$f"
    printf "__EOF_%s__\n" "${f//[.-]/_}"
  done
  sed -n '/^#@@FILES@@$/,$p' deploy/setup.template.sh | sed '1d'
} > "$out"
chmod +x "$out"
bash -n "$out" && echo "built $out ($(wc -l < "$out") lines)"
