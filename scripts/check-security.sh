#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v trivy >/dev/null
images=$(docker compose -f compose.yml config --images)
test -n "$images"
printf '%s\n' "$images" | sort -u | while IFS= read -r image; do
  trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$image"
done
