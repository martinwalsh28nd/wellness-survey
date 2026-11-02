#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 || -z "$1" || -z "$2" ]]; then
  printf 'Usage: %s BASE_URL RESULTS_KEY\n' "$0" >&2
  exit 2
fi

base_url=${1%/}
results_key=$2
case "$base_url" in
  http://*|https://*) ;;
  *) printf 'BASE_URL must start with http:// or https://\n' >&2; exit 2 ;;
esac

curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  --header 'Content-Type: application/json' \
  --data-binary '{"mentor":"yes","responsive":"no","health_time":"yes","fix_first":"D","free_text":"Smoke test response."}' \
  "$base_url/api/submit" >/dev/null

curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  --get --data-urlencode "key=$results_key" "$base_url/api/results" |
  python3 -c '
import json
import sys

try:
    count = json.load(sys.stdin)["n"]
    if type(count) is not int or count < 0:
        raise ValueError("invalid count")
except (ValueError, KeyError, TypeError):
    sys.exit("Results did not contain a valid response count.")
print(f"n={count}")
'
